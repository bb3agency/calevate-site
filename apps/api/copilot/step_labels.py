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
    "agent_settings": _l("Reading the agent's set-up", "Read the agent's set-up"),
    "agent_known_facts": _l("Checking what it knows by heart", "Checked what it knows by heart"),
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
    "agent_capture_fields_set_live": _l(
        "Changing what the live agent captures", "Changed what it captures"
    ),
    "agent_changes_apply": _l("Applying the agent's changes", "Applied the agent's changes"),
    "agent_deactivate": _l("Switching the agent off", "Switched the agent off"),
    "agent_delete": _l("Deleting the agent", "Deleted the agent"),
    "business_hours_set": _l("Setting your hours", "Set your hours"),
    "knowledge_link_add": _l("Adding a web page", "Added a web page"),
    "knowledge_remove": _l("Removing knowledge", "Removed knowledge"),
    "knowledge_rename": _l("Renaming knowledge", "Renamed knowledge"),
    "knowledge_note_save": _l("Saving a note", "Saved a note"),
    "number_buy": _l("Buying the number", "Bought the number"),
    "number_release": _l("Releasing the number", "Released the number"),
    "agent_test_call": _l("Placing a test call", "Placed a test call"),
    "business_profile_set": _l("Updating your business details", "Updated your business details"),
    "agent_script_suggest": _l("Preparing a script suggestion", "Prepared a script suggestion"),
    "agent_tests_fix": _l("Preparing fixes for the tests", "Prepared fixes for the tests"),
    "knowledge_teach": _l("Preparing what to teach", "Prepared what to teach"),
    "lead_fields_draft": _l("Preparing the lead details draft", "Prepared the lead details draft"),
    "business_copy_refresh": _l("Preparing to refresh your examples", "Asked for fresh examples"),
    "call_summarise_again": _l("Preparing a second summary", "Prepared a second summary"),
    "call_test_prepare": _l("Filling in the test form", "Filled in the test form"),
    "knowledge_facts_pin": _l("Preparing the answers to pin", "Prepared the answers to pin"),
    # D-893: the agent page's remaining buttons.
    "agent_restore": _l("Restoring the agent", "Restored the agent"),
    "agent_prepare": _l("Preparing to get the agent ready", "Prepared to get it ready"),
    "agent_script_put_live": _l("Preparing to put the script live", "Prepared to put it live"),
    "agent_script_discard": _l("Preparing to drop the saved change", "Prepared to drop it"),
    "agent_script_version_restore": _l(
        "Preparing to restore a script version", "Prepared to restore a version"
    ),
    "agent_settings_set": _l("Preparing the agent's settings", "Prepared the agent's settings"),
    "agent_handover_set": _l("Preparing the hand-over list", "Prepared the hand-over list"),
    "agent_action_set": _l("Preparing the in-call action", "Prepared the in-call action"),
    "agent_action_switch": _l("Preparing to switch the action", "Prepared to switch it"),
    "agent_action_remove": _l("Preparing to remove the action", "Prepared to remove it"),
    "lead_fields_keep_draft": _l("Preparing the lead details", "Prepared the lead details"),
    "lead_fields_reset": _l("Preparing the standard lead details", "Prepared the lead details"),
    "lead_suggestion_answer": _l("Preparing your answer", "Prepared your answer"),
    # D-893 lane L6: the account's own settings.
    "billing_settings": _l("Checking your billing settings", "Checked your billing settings"),
    "number_assign": _l("Preparing the number change", "Prepared the number change"),
    "forwarding_line_add": _l("Preparing to add your number", "Prepared to add your number"),
    "forwarding_line_change": _l("Changing how it forwards", "Changed how it forwards"),
    "forwarding_line_remove": _l("Preparing to remove the number", "Prepared the removal"),
    "forwarding_line_test": _l("Preparing a forwarding test", "Prepared a forwarding test"),
    "team_invite": _l("Preparing the invitation", "Prepared the invitation"),
    "team_member_role": _l("Preparing the role change", "Prepared the role change"),
    "team_member_remove": _l("Preparing to remove them", "Prepared the removal"),
    "team_invitation": _l("Preparing the invitation change", "Prepared the invitation change"),
    "line_protection_phone": _l("Preparing the backup phone", "Prepared the backup phone"),
    "lead_source_create": _l("Preparing the lead source", "Prepared the lead source"),
    "lead_source_edit": _l("Changing the lead source's agent", "Changed the lead source's agent"),
    "lead_source_switch": _l("Switching the lead source", "Switched the lead source"),
    "lead_source_rotate": _l("Preparing a new secret", "Prepared a new secret"),
    "lead_calling_rules": _l("Preparing the calling rules", "Prepared the calling rules"),
    "held_lead_decide": _l("Preparing the held lead", "Prepared the held lead"),
    "crm_endpoint_create": _l("Preparing the connection", "Prepared the connection"),
    "crm_endpoint_edit": _l("Preparing the connection change", "Prepared the connection change"),
    "crm_endpoint_act": _l("Preparing the connection change", "Prepared the connection change"),
    "crm_delivery_resend": _l("Preparing to resend", "Prepared the resend"),
    "spend_caps_set": _l("Preparing your spending limit", "Prepared your spending limit"),
    "auto_recharge_set": _l("Preparing the auto-recharge change", "Prepared the change"),
    "low_balance_alert_set": _l("Setting the low-credit warning", "Set the low-credit warning"),
    "ai_allowance_extra": _l("Preparing more AI help", "Prepared more AI help"),
    "knowledge_questions": _l(
        "Checking the questions to answer", "Checked the questions to answer"
    ),
    "knowledge_question_settle": _l("Preparing the answer", "Prepared the answer"),
    "knowledge_fact_change": _l("Preparing the fact change", "Prepared the fact change"),
    "agent_tests_run": _l("Preparing the practice tests", "Prepared the practice tests"),
    "agent_test_add": _l("Saving the practice test", "Saved the practice test"),
    "callbacks_book_bulk": _l("Preparing the call-backs", "Prepared the call-backs"),
    "calls_place_bulk": _l("Preparing the calls", "Prepared the calls"),
    "call_back": _l("Preparing the call-back", "Prepared the call-back"),
    "call_follow_up_set": _l("Marking the call", "Marked the call"),
    "call_translate": _l("Preparing the English", "Prepared the English"),
    "lead_whatsapp_send": _l("Preparing the message", "Prepared the message"),
    "callbacks_change_bulk": _l("Preparing the call-back changes", "Prepared the changes"),
    "campaign_edit": _l("Changing the campaign", "Changed the campaign"),
    "campaign_repeat": _l("Preparing the repeat", "Prepared the repeat"),
    "campaign_stop": _l("Preparing to stop the campaign", "Prepared to stop the campaign"),
    "campaign_delete": _l("Preparing to delete the draft", "Prepared to delete the draft"),
    "campaign_contacts_add": _l("Preparing the people to add", "Prepared the people to add"),
    "campaign_contacts_remove": _l(
        "Preparing the people to take off", "Prepared the people to take off"
    ),
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
    "admin_client_standing": _l("Checking the client's standing", "Checked the client's standing"),
    "platform_halt_outbound": _l("Halting outgoing calls", "Halted outgoing calls"),
    "admin_kyc_review": _l("Recording the verification decision", "Recorded the decision"),
    "admin_workspace_provision": _l("Setting up the workspace", "Set up the workspace"),
    "admin_number_release": _l("Releasing the number", "Released the number"),
    "admin_voice_set": _l("Changing the voice", "Changed the voice"),
    "healer_incidents": _l("Checking the healer's problems", "Checked the healer's problems"),
    "healer_incident": _l("Reading the problem's history", "Read the problem's history"),
    "healer_money_review": _l("Comparing charges with our records", "Compared the charges"),
    "healer_retry": _l("Running the repair again", "Ran the repair again"),
    "healer_resolve": _l("Marking the problem handled", "Marked the problem handled"),
    "healer_attest_rate": _l("Recording the rate you read", "Recorded the rate"),
}

#: An area call (D-893) is shown under the registry name it resolves to; the area's own
#: name reaches the panel only when the call named no action it has.
_AREA_WORDS: Final[dict[str, str]] = {
    "calls": "calls",
    "callbacks": "call-backs",
    "leads": "leads",
    "campaigns": "campaigns",
    "agents": "agents",
    "knowledge": "knowledge",
    "numbers": "numbers",
    "team": "team",
    "settings": "settings",
    "integrations": "connections",
    "billing": "billing",
    "reports": "reports",
    "routines": "repeating jobs",
}
for _area, _words in _AREA_WORDS.items():
    STEP_LABELS[f"{_area}_find"] = _l(f"Looking up your {_words}", f"Looked up your {_words}")
    STEP_LABELS[f"{_area}_do"] = _l(f"Working on your {_words}", f"Worked on your {_words}")

UNKNOWN: Final[StepLabel] = _l("Trying something", "Tried something it could not do")


def step_label(tool: str, *, running: bool) -> str:
    label = STEP_LABELS.get(tool, UNKNOWN)
    return label.running if running else label.done


__all__ = ["STEP_LABELS", "UNKNOWN", "StepLabel", "step_label"]
