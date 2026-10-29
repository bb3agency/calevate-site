"""Pip's model-facing tools, grouped by AREA (D-893 F1).

The registry is unchanged: every read is a `tools.ReadTool`, every action an
`actions.ActionTool` with its own tier, permission, planner, executor, Undo and audit. What
changes is what the MODEL sees. Instead of one schema per tool (about seventy, most of the
cacheable prefix), each area is offered as two tools:

* `<area>_find` — `{"action": <a read tool's name>, "args": {...}}`
* `<area>_do`   — `{"action": <an action tool's name>, "args": {...}}`

`resolve` turns such a call back into the registry call it names before the loop looks at
it, so `write_tools.tier_of`, `plan_write`, `run_immediate`, `stage_for_approval` and
`tools.run_read_tool` see exactly the call they saw before. The tier is still read only from
the registry; nothing here can make an action immediate.

Why two tools per area rather than one per tool or one for everything: Anthropic's "Writing
effective tools for agents" recommends few, workflow-shaped tools with readable arguments
and errors that say how to fix the call; one tool for everything would put the whole
catalogue in one description the model must search, and seventy tools cost ~13k tokens on
every request (PIP-AGENT-PLAN §2a). An area is how a person thinks about the console.

The model sees, per action, one line: its name, its argument names, `now` or `confirm`, and
what it is for. The `args` object lists every argument name of the area with its type and
enum, without descriptions; a call with a wrong argument is refused with that action's
COMPLETE schema (descriptions included), so the model corrects itself on the next turn.

`args` is not strict: its shape depends on `action`, which a strict schema cannot say
(every property would have to be required). The server validates it here instead, against
the action's own schema, as it validated a strict call before (`tools.py`, `write_tools.py`
never trusted `strict`).

Adding a tool is one more line in `ENTRIES` (COPILOT-CONTRACT §2a). `areas_test.py` fails
when a registered tool has no area, so the registration cannot be forgotten.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from apps.api.copilot.actions import ActionTool
from apps.api.copilot.prompt import function_tool
from apps.api.copilot.tools import ReadTool
from apps.workers import chat

Area = Literal[
    "calls",
    "callbacks",
    "leads",
    "campaigns",
    "agents",
    "knowledge",
    "numbers",
    "team",
    "settings",
    "integrations",
    "billing",
    "reports",
    "routines",
]

#: Wire order of the areas. Part of the cacheable prefix: append, never reorder.
AREAS: Final[tuple[Area, ...]] = (
    "calls",
    "callbacks",
    "leads",
    "campaigns",
    "agents",
    "knowledge",
    "numbers",
    "team",
    "settings",
    "integrations",
    "billing",
    "reports",
    "routines",
)

FIND: Final = "_find"
DO: Final = "_do"


@dataclass(frozen=True, slots=True)
class AreaEntry:
    """One registered tool's place on the model-facing surface.

    `line` is what the model reads about it, after the generated `name(args) now|confirm:`.
    One short clause: what it does, and the sibling to use instead where two overlap.
    """

    tool: str
    area: Area
    line: str


#: What each area's two tools are for, in a few words. An area with no read tool offers no
#: `_find`, and one with no action no `_do`.
INTROS: Final[dict[Area, tuple[str, str]]] = {
    "calls": ("Look up calls.", "Act on calls."),
    "callbacks": ("Look up call-backs.", "Book, move or cancel call-backs."),
    "leads": ("Look up leads.", "Change leads and the do-not-call list."),
    "campaigns": ("Look up outbound campaigns.", "Create and run outbound campaigns."),
    "agents": ("Look up voice agents.", "Create, change, publish and pause voice agents."),
    "knowledge": ("Look up what the agents know.", "Change what the agents know."),
    "numbers": ("Look up phone numbers.", "Buy, release and assign numbers; forwarded lines."),
    "team": ("Look up the team.", "Change the team."),
    "settings": ("Look up account settings.", "Change business details and settings."),
    "integrations": ("Look up lead sources and connections.", "Change lead sources, connections."),
    "billing": ("Look up credit and statements.", "Change billing settings (never pay)."),
    "reports": (
        "Numbers, charts, quality, what needs attention.",
        "Pin charts to the home screen.",
    ),
    "routines": ("Look up repeating jobs.", "Create and change repeating jobs."),
}

#: Every registered tool, by area. APPEND ONLY: the order inside an area is wire order.
ENTRIES: Final[tuple[AreaEntry, ...]] = (
    # --- reads --------------------------------------------------------------------------
    AreaEntry(
        "business_snapshot",
        "reports",
        "counts over every call, by day/week/month or per caller (repeats)/outcome/agent",
    ),
    AreaEntry(
        "leads_search",
        "leads",
        "leads by filters or name, with counts; by what they asked: leads_semantic_search",
    ),
    AreaEntry(
        "leads_semantic_search", "leads", "leads by what they asked for; names use leads_search"
    ),
    AreaEntry(
        "calls_recent", "calls", "calls by time and outcome; what callers said: search_calls"
    ),
    AreaEntry("campaigns_list", "campaigns", "every campaign, status and what blocks launch"),
    AreaEntry("agents_list", "agents", "every agent and whether it is live"),
    AreaEntry(
        "search_knowledge",
        "knowledge",
        "what the agents tell callers; scope everything: all the business gave, each hit "
        "saying if agents use it; what callers said: calls_find search_calls",
    ),
    AreaEntry(
        "search_calls",
        "calls",
        "what callers said, by meaning; by time: calls_recent; agents: search_knowledge",
    ),
    AreaEntry("agent_detail", "agents", "one agent in full"),
    AreaEntry("lead_detail", "leads", "one lead in full"),
    AreaEntry("call_detail", "calls", "one call in full, redacted transcript"),
    AreaEntry("calls_live", "calls", "calls in progress now"),
    AreaEntry("callbacks_list", "callbacks", "call-backs, when due and their state"),
    AreaEntry(
        "knowledge_sources",
        "knowledge",
        "facts, notes, files, photos, links, rules and the profile, each with its state and "
        "[ref]; `find` = words in a name, or a [ref] to read it a page at a time",
    ),
    AreaEntry("numbers_list", "numbers", "the account's numbers and their agents"),
    AreaEntry("numbers_available", "numbers", "cities with numbers to buy"),
    AreaEntry(
        "billing_overview", "billing", "credit balance and statements; limits: billing_settings"
    ),
    AreaEntry("verification_status", "settings", "verification, pledge and profile still needed"),
    AreaEntry("integrations_status", "integrations", "lead sources, connections, failures"),
    AreaEntry("needs_attention", "reports", "what needs attention now"),
    AreaEntry("quality_reports", "reports", "latest quality checks of the agents"),
    AreaEntry("campaign_detail", "campaigns", "one campaign in full and what blocks it"),
    AreaEntry("team_members", "team", "the people on the team, with user ids"),
    AreaEntry("voices_offered", "agents", "voices an agent can use, with voice ids"),
    # --- actions ------------------------------------------------------------------------
    AreaEntry("lead_set_status", "leads", "one lead's status; many leads: leads_bulk_update"),
    AreaEntry("dnc_add", "leads", "stop calling one lead's number"),
    AreaEntry("campaign_pause", "campaigns", "pause a running campaign; for good: campaign_stop"),
    AreaEntry(
        "propose_knowledge",
        "knowledge",
        "add one fact the person just told you; a longer text: knowledge_teach",
    ),
    AreaEntry("agent_create", "agents", "a new draft agent; ask name, direction, language first"),
    AreaEntry("agent_rename", "agents", "the agent's dashboard name"),
    AreaEntry("agent_publish", "agents", "put an agent live; to try in chat only: agent_prepare"),
    AreaEntry("campaign_launch", "campaigns", "start calling a campaign's contacts"),
    AreaEntry("lead_assign", "leads", "give one lead to a team member (user_id null: nobody)"),
    AreaEntry("lead_rename", "leads", "correct one lead's name"),
    AreaEntry(
        "leads_bulk_update",
        "leads",
        "status or owner of many leads by `lens` or lead_ids; one lead: lead_set_status",
    ),
    AreaEntry("dnc_remove", "leads", "take a lead off do-not-call (hand-added only)"),
    AreaEntry(
        "call_place",
        "calls",
        "an agent calls one lead now; free trial: agent_test_call; many: calls_place_bulk",
    ),
    AreaEntry(
        "callback_book",
        "callbacks",
        "call one lead back at a time (IST); many: callbacks_book_bulk",
    ),
    AreaEntry("callback_reschedule", "callbacks", "move a waiting call-back"),
    AreaEntry("callback_cancel", "callbacks", "cancel a waiting call-back"),
    AreaEntry("campaign_create", "campaigns", "a new draft campaign"),
    AreaEntry("campaign_clone", "campaigns", "copy a campaign's settings into a new draft"),
    AreaEntry(
        "campaign_add_leads",
        "campaigns",
        "add leads to a draft campaign, by `lens` or lead_ids; a list: campaign_contacts_add",
    ),
    AreaEntry("campaign_schedule", "campaigns", "start a draft campaign later"),
    AreaEntry("campaign_unschedule", "campaigns", "cancel a scheduled start"),
    AreaEntry("campaign_resume", "campaigns", "resume a paused campaign"),
    AreaEntry(
        "agent_edit",
        "agents",
        "language, voice, opening line or notices of a draft or paused agent; live: "
        "agent_edit_live",
    ),
    AreaEntry("agent_edit_live", "agents", "the same for a live agent; not live: agent_edit"),
    AreaEntry(
        "agent_capture_fields_set",
        "agents",
        "the WHOLE list of details a draft or paused agent writes down; live: "
        "agent_capture_fields_set_live",
    ),
    AreaEntry(
        "agent_capture_fields_set_live",
        "agents",
        "the same for a live agent; not live: agent_capture_fields_set",
    ),
    AreaEntry(
        "agent_changes_apply",
        "agents",
        "put a live agent's saved change live; drop it: agent_script_discard; a reviewed "
        "draft: agent_script_put_live",
    ),
    AreaEntry("agent_deactivate", "agents", "pause a live agent"),
    AreaEntry("agent_delete", "agents", "delete an agent that is not live"),
    AreaEntry("business_hours_set", "settings", "opening hours, all seven days"),
    AreaEntry("knowledge_link_add", "knowledge", "add a web page the person gave"),
    AreaEntry(
        "knowledge_remove",
        "knowledge",
        "remove a file, photo, link or note by [ref]; put_back restores a removed note",
    ),
    AreaEntry("number_buy", "numbers", "rent a number in a city; spends credit"),
    AreaEntry("number_release", "numbers", "give up a number"),
    AreaEntry(
        "agent_test_call", "agents", "free-trial test call to one lead; paying account: call_place"
    ),
    AreaEntry(
        "business_profile_set",
        "settings",
        "replace WHOLE profile sections",
    ),
    AreaEntry(
        "agent_script_suggest",
        "agents",
        "suggest a script change (change), a whole script from the five answers (whole), "
        "or steps (steps); failed tests: agent_tests_fix; a dictated value: set_fields",
    ),
    AreaEntry(
        "agent_tests_fix",
        "agents",
        "fixes for failed tests; a change they describe: agent_script_suggest",
    ),
    AreaEntry(
        "knowledge_teach",
        "knowledge",
        "teach from what they typed or attached; one fact: propose_knowledge",
    ),
    AreaEntry("lead_fields_draft", "settings", "draft a custom business's lead details once"),
    AreaEntry(
        "call_summarise_again", "calls", "a fresh summary of one call; to read it: call_detail"
    ),
    AreaEntry("call_test_prepare", "calls", "make one call a test for its agent"),
    AreaEntry("business_copy_refresh", "settings", "rewrite the account's examples"),
    AreaEntry(
        "knowledge_facts_pin", "knowledge", "pin up to three questions with the owner's answers"
    ),
    # D-893 F3: plan-backed actions over a set.
    AreaEntry(
        "callbacks_book_bulk",
        "callbacks",
        "call-backs for many leads at one time, by `lens` or lead_ids; one lead: callback_book",
    ),
    AreaEntry(
        "calls_place_bulk",
        "calls",
        "an agent calls many leads as a campaign, by `lens` or lead_ids; ask consent_source; "
        "retry unanswered: lens last_outcome missed; one lead now: call_place",
    ),
    # D-893 lanes L4-L8: reads.
    AreaEntry(
        "agent_settings",
        "agents",
        "one part of an agent's set-up, with the ids its actions take",
    ),
    AreaEntry(
        "billing_settings",
        "billing",
        "spending limits, auto-recharge, low-credit warning; balance: billing_overview",
    ),
    AreaEntry(
        "knowledge_questions", "knowledge", "questions the agents need answered, with drafts"
    ),
    AreaEntry(
        "agent_known_facts", "knowledge", "facts one agent answers at once and how many it looks up"
    ),
    # D-893 L4: the agent page's buttons.
    AreaEntry("agent_restore", "agents", "bring a deleted agent back, paused"),
    AreaEntry(
        "agent_prepare",
        "agents",
        "get a draft or paused agent ready to try in chat; on the phone: agent_publish",
    ),
    AreaEntry(
        "agent_script_put_live",
        "agents",
        "save the reviewed script draft and put it live; a waiting change: agent_changes_apply",
    ),
    AreaEntry(
        "agent_script_discard",
        "agents",
        "drop a live agent's saved script change; put it live: agent_changes_apply",
    ),
    AreaEntry(
        "agent_script_version_restore", "agents", "copy an earlier script version to the draft"
    ),
    AreaEntry(
        "agent_settings_set",
        "agents",
        "how it sounds and handles calls, longest call, AI model, caller memory, screen guide",
    ),
    AreaEntry("agent_handover_set", "agents", "who it may put a caller through to, in order"),
    AreaEntry("agent_action_set", "agents", "add (action_id null) or change an in-call action"),
    AreaEntry("agent_action_switch", "agents", "switch one in-call action, or all, on or off"),
    AreaEntry("agent_action_remove", "agents", "remove an in-call action"),
    AreaEntry("lead_fields_keep_draft", "agents", "keep some lead details lead_fields_draft made"),
    AreaEntry("lead_fields_reset", "agents", "lead details back to the standard set"),
    AreaEntry("lead_suggestion_answer", "agents", "accept or turn down a lead-detail suggestion"),
    # D-893 L6: the account's own settings. Lead sources sit with integrations because
    # `integrations_status` is the read that names their ids.
    AreaEntry("number_assign", "numbers", "which agent uses one of the numbers, or none"),
    AreaEntry("forwarding_line_add", "numbers", "track an existing number forwarded here"),
    AreaEntry("forwarding_line_change", "numbers", "how a tracked number forwards"),
    AreaEntry("forwarding_line_remove", "numbers", "stop tracking an existing number"),
    AreaEntry("forwarding_line_test", "numbers", "a test call to a tracked number"),
    AreaEntry("team_invite", "team", "email an invitation"),
    AreaEntry("team_member_role", "team", "change a member's role"),
    AreaEntry("team_member_remove", "team", "remove a member"),
    AreaEntry("team_invitation", "team", "resend or cancel an invitation"),
    AreaEntry("line_protection_phone", "settings", "backup phone when the agent cannot answer"),
    AreaEntry("lead_source_create", "integrations", "a new lead source address"),
    AreaEntry("lead_source_edit", "integrations", "which agent answers a lead source"),
    AreaEntry("lead_source_switch", "integrations", "pause or resume a lead source"),
    AreaEntry("lead_source_rotate", "integrations", "a new secret for a lead source"),
    AreaEntry("lead_calling_rules", "integrations", "when and how new leads are called"),
    AreaEntry("held_lead_decide", "integrations", "call or drop a lead held after hours"),
    AreaEntry("crm_endpoint_create", "integrations", "send events to a webhook address"),
    AreaEntry("crm_endpoint_edit", "integrations", "an endpoint's events or opt-ins"),
    AreaEntry("crm_endpoint_act", "integrations", "switch an endpoint off or re-key it"),
    AreaEntry("crm_delivery_resend", "integrations", "resend a failed delivery"),
    AreaEntry("spend_caps_set", "billing", "monthly spending and minute limits"),
    AreaEntry("auto_recharge_set", "billing", "auto-recharge on, off or its amounts"),
    AreaEntry("low_balance_alert_set", "billing", "the low-credit warning amount"),
    AreaEntry("ai_allowance_extra", "billing", "extra AI help this month, paid from credit"),
    # D-893 L8 and L5: the knowledge store, guided questions and practice tests.
    AreaEntry("knowledge_rename", "knowledge", "rename a file, link or note"),
    AreaEntry(
        "knowledge_note_save",
        "knowledge",
        "a note's new text, or a note correcting a file or link",
    ),
    AreaEntry(
        "knowledge_question_settle",
        "knowledge",
        "answer a question in their words; null dismisses it",
    ),
    AreaEntry("knowledge_fact_change", "knowledge", "edit, pin, unpin, move or remove one fact"),
    AreaEntry("agent_tests_run", "agents", "run an agent's practice tests"),
    AreaEntry(
        "agent_test_add",
        "agents",
        "save a hand-written practice test; from a call: call_test_prepare",
    ),
    # D-893 L1: calls and call-backs.
    AreaEntry("call_back", "calls", "the call's agent rings them now with that call's context"),
    AreaEntry("call_follow_up_set", "calls", "mark a call done (resolved), needs_you or null"),
    AreaEntry("call_translate", "calls", "make a call's failed English again"),
    AreaEntry(
        "lead_whatsapp_send", "calls", "approved WhatsApp to one lead; no template_id lists them"
    ),
    AreaEntry("callbacks_change_bulk", "callbacks", "move or cancel many waiting call-backs"),
    # D-893 L3: the campaign screen's remaining buttons.
    AreaEntry("campaign_edit", "campaigns", "a draft's name, agent, pace, hours or tries"),
    AreaEntry("campaign_repeat", "campaigns", "start it every week on these days (1=Mon)"),
    AreaEntry(
        "campaign_stop",
        "campaigns",
        "end for good; for now: campaign_pause; draft: campaign_delete",
    ),
    AreaEntry("campaign_delete", "campaigns", "delete a draft; launched: campaign_stop"),
    AreaEntry(
        "campaign_contacts_add",
        "campaigns",
        "people from a pasted or attached list; leads: campaign_add_leads",
    ),
    AreaEntry("campaign_contacts_remove", "campaigns", "take people off before they are called"),
    AreaEntry("campaign_consent_set", "campaigns", "where the list's permission came from"),
    # D-893 L7: the person's routines.
    AreaEntry("routines_list", "routines", "their routines with ids"),
    AreaEntry("routine_create", "routines", "set up a repeating job"),
    AreaEntry("routine_edit", "routines", "change, pause (on false) or resume one"),
    AreaEntry("routine_delete", "routines", "delete one"),
    # D-893 L2: leads, do-not-call, saved views, exports and lead-source fields.
    AreaEntry("lead_source_mapping", "integrations", "which form fields a lead source reads"),
    AreaEntry("dnc_restore", "leads", "lift a lead's own opt-out on their word"),
    AreaEntry("lead_view_save", "leads", "save `lens` as a named view"),
    AreaEntry("leads_export", "leads", "spreadsheet of the `lens` leads"),
    AreaEntry("calls_export", "calls", "spreadsheet of the `call_lens` calls"),
    # D-935: troubleshoot mode. Each runs ordered checks and names the first cause and fix.
    AreaEntry("agent_diagnose", "agents", "why it does not pick up or answer"),
    AreaEntry("call_diagnose", "calls", "why one call failed"),
    AreaEntry("campaign_diagnose", "campaigns", "why it is not calling"),
    AreaEntry(
        "delivery_diagnose", "integrations", "why a lead did not reach a Sheet, webhook or WhatsApp"
    ),
    AreaEntry("knowledge_diagnose", "knowledge", "why agents do not use what they were given"),
    # D-938: the coverage audit's missing buttons and "how do I" (`coverage_actions.py`).
    AreaEntry("help_lookup", "settings", "how to do anything in Calevate: screen, term, action"),
    AreaEntry("connection_check", "integrations", "does a connected account still work"),
    AreaEntry(
        "account_model_tier_set", "settings", "AI model tier of agents with none of their own"
    ),
    AreaEntry(
        "agent_team_alert_set", "agents", "when it tells the team of a caller; ids: part handover"
    ),
    AreaEntry("team_alert_contact", "team", "add, remove, make default a team alert email"),
    AreaEntry("knowledge_refresh", "knowledge", "approve a waiting file or link, or read it again"),
    AreaEntry("connection_disconnect", "integrations", "disconnect a connected account"),
    AreaEntry(
        "account_switch_set",
        "settings",
        "staff may edit knowledge, call only opted-in, save-our-number WhatsApp",
    ),
    # D-934: charts and tables drawn in the panel, and cards kept on the home screen.
    AreaEntry("report_chart", "reports", "chart or table for the person; to keep it: chart_pin"),
    AreaEntry("chart_pin", "reports", "keep a report_chart on the home screen"),
    AreaEntry("chart_unpin", "reports", "remove a home card by name"),
)

AREA_OF: Final[dict[str, Area]] = {entry.tool: entry.area for entry in ENTRIES}
ENTRY_LINES: Final[dict[str, str]] = {entry.tool: entry.line for entry in ENTRIES}


def find_name(area: Area) -> str:
    return f"{area}{FIND}"


def do_name(area: Area) -> str:
    return f"{area}{DO}"


class AreaCallError(Exception):
    """An area call that names no action or carries arguments that action does not take.

    `reason` goes back to the model as the tool result; it names fields and shapes, never a
    value (hard rule 6), and ends with the schema the model should have used."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class _Action:
    name: str
    kind: Literal["find", "do"]
    parameters: Mapping[str, Any]
    #: `now`, `confirm`, or `read`.
    marker: str


# --- the schema subset the registry uses, validated -----------------------------------------

_JSON_TYPES: Final[dict[str, tuple[type, ...]]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
    "null": (type(None),),
}


def _problems(schema: Mapping[str, Any], value: Any, path: str) -> list[str]:
    """Why `value` does not fit `schema`, as sentences naming the path only.

    The subset the registry's schemas use (`actions.action_schema`, `tools.ReadTool`):
    `type`, `enum`, `anyOf`, `items`, `properties`, `required`, `additionalProperties`.
    A keyword outside it is not checked here; the tool's own `parse_args` still runs."""
    if "anyOf" in schema:
        if any(not _problems(option, value, path) for option in schema["anyOf"]):
            return []
        # An object that fails its object form is told what inside it is wrong, which is
        # what the model can fix; "wrong type" alone sends it back to guess.
        shape = _object_schema(schema)
        if isinstance(value, dict) and shape is not None:
            return _object_problems(shape, value, path)
        return [f"`{path}` has the wrong type"]
    kind = schema.get("type")
    if isinstance(kind, str) and kind in _JSON_TYPES:
        allowed = _JSON_TYPES[kind]
        # bool is an int in Python; JSON keeps them apart.
        if isinstance(value, bool) and kind in ("integer", "number"):
            return [f"`{path}` should be a {kind}"]
        if not isinstance(value, allowed):
            return [f"`{path}` should be a {kind}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"`{path}` must be one of: {', '.join(map(str, schema['enum']))}"]
    if isinstance(value, list) and isinstance(schema.get("items"), Mapping):
        found: list[str] = []
        for index, item in enumerate(value):
            found += _problems(schema["items"], item, f"{path}[{index}]")
        return found
    if isinstance(value, dict) and "properties" in schema:
        return _object_problems(schema, value, path)
    return []


def _object_problems(schema: Mapping[str, Any], value: Mapping[str, Any], path: str) -> list[str]:
    properties: Mapping[str, Any] = schema.get("properties", {})
    prefix = f"{path}." if path else ""
    found = [
        f"`{prefix}{key}` is required" for key in schema.get("required", []) if key not in value
    ]
    if schema.get("additionalProperties") is False:
        found += [f"`{prefix}{key}` is not an argument" for key in value if key not in properties]
    for key, item in value.items():
        if key in properties:
            found += _problems(properties[key], item, f"{prefix}{key}")
    return found


def _nullable(schema: Mapping[str, Any]) -> bool:
    if schema.get("type") == "null":
        return True
    return any(_nullable(option) for option in schema.get("anyOf", ()))


def _objects_from_text(parameters: Mapping[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
    """`args` with an object argument the model sent as JSON text read as the object.

    A lens read hands the model its lens as a JSON handle to copy into the action
    (`tools._handle_line`), and models copy it as the string it was shown. Text that is not
    a JSON object is left as it was, so the check below still names it."""
    fixed = dict(args)
    properties: Mapping[str, Any] = parameters.get("properties", {})
    for key, value in args.items():
        if not isinstance(value, str) or _object_schema(properties.get(key, {})) is None:
            continue
        try:
            parsed = json.loads(value)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            fixed[key] = parsed
    return fixed


def _with_nulls(parameters: Mapping[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
    """`args` with every omitted argument that may be null set to null.

    The registry's schemas list every argument as required and spell "optional" as
    nullable (`actions.action_schema`), so the model may leave those out here."""
    filled = dict(args)
    properties: Mapping[str, Any] = parameters.get("properties", {})
    for key in parameters.get("required", []):
        if key not in filled and _nullable(properties.get(key, {})):
            filled[key] = None
    for key, value in list(filled.items()):
        nested = _object_schema(properties.get(key, {}))
        if isinstance(value, dict) and nested is not None:
            filled[key] = _with_nulls(nested, value)
    return filled


def _object_schema(schema: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The object form of a property schema (itself, or its object alternative)."""
    if schema.get("type") == "object" and "properties" in schema:
        return schema
    return next(
        (
            option
            for option in schema.get("anyOf", ())
            if option.get("type") == "object" and "properties" in option
        ),
        None,
    )


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


# --- the surface -----------------------------------------------------------------------------


def _undescribed(value: Any) -> Any:
    """A schema with every `description` removed, at any depth: the action line and the
    refusal's full schema carry the meaning, and descriptions inside a nested lens would
    otherwise be paid once per area that takes it."""
    if isinstance(value, Mapping):
        options = value.get("anyOf")
        if isinstance(options, list):
            # "X or null" is shown as X: an argument that may be null may be left out
            # (`_with_nulls`), and the validation reads the action's own schema.
            kept = [option for option in options if option != {"type": "null"}]
            if len(kept) == 1 and len(kept) < len(options):
                return _undescribed(kept[0])
        return {key: _undescribed(item) for key, item in value.items() if key != "description"}
    if isinstance(value, list):
        return [_undescribed(item) for item in value]
    return value


def _alternatives(schema: Mapping[str, Any]) -> list[dict[str, Any]]:
    bare = _undescribed(schema)
    if set(bare) == {"anyOf"}:
        return [dict(option) for option in bare["anyOf"]]
    return [bare]


def _merged(schemas: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """One property schema accepting every shape the same argument name takes in an area,
    without its description (the action line and the refusal carry the meaning)."""
    seen: dict[str, dict[str, Any]] = {}
    for schema in schemas:
        for option in _alternatives(schema):
            seen.setdefault(_compact(option), option)
    options = list(seen.values())
    return options[0] if len(options) == 1 else {"anyOf": options}


def _signature(name: str, parameters: Mapping[str, Any]) -> str:
    properties: Mapping[str, Any] = parameters.get("properties", {})
    return f"{name}({', '.join(properties)})"


def _area_tool(
    area: Area, kind: Literal["find", "do"], actions: Sequence[_Action]
) -> dict[str, Any]:
    intro = INTROS[area][0 if kind == "find" else 1]
    lines = [
        f"- {_signature(action.name, action.parameters)}"
        + ("" if action.marker == "read" else f" {action.marker}")
        + f": {ENTRY_LINES[action.name]}"
        for action in actions
    ]
    by_name: dict[str, list[Mapping[str, Any]]] = {}
    for action in actions:
        for key, schema in action.parameters.get("properties", {}).items():
            by_name.setdefault(key, []).append(schema)
    tool = function_tool(
        name=find_name(area) if kind == "find" else do_name(area),
        # How to call an area tool (`action` plus `args`) is said once, in the system prompt,
        # rather than in each of the ~26 area descriptions (D-938 paid for its actions so).
        description=f"{intro}\n" + "\n".join(lines),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": [action.name for action in actions]},
                "args": {
                    "type": "object",
                    "properties": {key: _merged(found) for key, found in by_name.items()},
                    "additionalProperties": False,
                },
            },
            "required": ["action", "args"],
            "additionalProperties": False,
        },
    )
    tool["function"]["strict"] = False
    return tool


@dataclass(frozen=True, slots=True)
class AreaSurface:
    """The client realm's area tools and how to turn a call on one back into a registry call.

    Built once per process from the registries (`service.area_surface`); every request of
    the realm gets the same `tools` list, so the cacheable prefix stays byte-identical."""

    tools: tuple[Mapping[str, Any], ...]
    actions: Mapping[str, Mapping[str, _Action]]

    @property
    def find_names(self) -> frozenset[str]:
        return frozenset(name for name in self.actions if name.endswith(FIND))

    def is_area_tool(self, name: str) -> bool:
        return name in self.actions

    def labels(self) -> frozenset[str]:
        """Every `<area tool>:<action>` the surface offers, for the tool-choice eval."""
        return frozenset(f"{wire}:{name}" for wire, acts in self.actions.items() for name in acts)

    def label_of(self, call: chat.ToolCall) -> str:
        """`<area tool>:<action>` for an area call whose action can be read, else the name."""
        if call.name not in self.actions:
            return call.name
        try:
            body = json.loads(call.arguments or "")
        except ValueError:
            return call.name
        action = body.get("action") if isinstance(body, dict) else None
        return f"{call.name}:{action}" if isinstance(action, str) else call.name

    def resolve(self, call: chat.ToolCall) -> chat.ToolCall:
        """The registry call an area call names, carrying the original as `wire`.

        A call that is not an area call is returned unchanged. Raises `AreaCallError` with
        the sentence the model should read when the action or its arguments are wrong."""
        acts = self.actions.get(call.name)
        if acts is None:
            return call
        try:
            body = json.loads(call.arguments or "")
        except ValueError as exc:
            raise AreaCallError(f"the `{call.name}` call was not valid JSON") from exc
        if not isinstance(body, dict):
            raise AreaCallError(f"the `{call.name}` call was not an object")
        name = body.get("action")
        if not isinstance(name, str) or name not in acts:
            raise AreaCallError(
                f"`{call.name}` has no action of that name; its actions are: " + ", ".join(acts)
            )
        action = acts[name]
        raw_args = body.get("args", {})
        if raw_args is None:
            raw_args = {}
        if not isinstance(raw_args, dict):
            raise AreaCallError(f"`args` of `{call.name}` must be an object")
        args = _with_nulls(action.parameters, _objects_from_text(action.parameters, raw_args))
        found = _problems(action.parameters, args, "")
        if found:
            raise AreaCallError(
                f"`{call.name}` action `{name}` was not run: "
                + "; ".join(found[:5])
                + f". Its args are: {_compact(action.parameters)}"
            )
        return dataclasses.replace(call, name=name, arguments=_compact(args), wire=call)


def build_surface(reads: Sequence[ReadTool], writes: Sequence[ActionTool]) -> AreaSurface:
    """The area tools for these registries, in `AREAS` order. Refuses a tool with no area,
    and an area entry naming a tool that is not registered."""
    registered = [tool.name for tool in reads] + [tool.name for tool in writes]
    missing = [name for name in registered if name not in AREA_OF]
    if missing:
        raise ValueError(f"no area for {', '.join(missing)}: add it to areas.ENTRIES")
    stale = sorted(set(AREA_OF) - set(registered))
    if stale:
        raise ValueError(f"areas.ENTRIES names unregistered tools: {', '.join(stale)}")
    order = {entry.tool: index for index, entry in enumerate(ENTRIES)}
    finds: dict[Area, list[_Action]] = {}
    dos: dict[Area, list[_Action]] = {}
    for read in reads:
        finds.setdefault(AREA_OF[read.name], []).append(
            _Action(read.name, "find", read.parameters, "read")
        )
    for write in writes:
        dos.setdefault(AREA_OF[write.name], []).append(
            _Action(
                write.name,
                "do",
                write.schema["function"]["parameters"],
                "now" if write.tier == "immediate" else "confirm",
            )
        )
    tools: list[Mapping[str, Any]] = []
    actions: dict[str, dict[str, _Action]] = {}
    for area in AREAS:
        for kind, group in (("find", finds.get(area)), ("do", dos.get(area))):
            if not group:
                continue
            group.sort(key=lambda action: order[action.name])
            tool = _area_tool(area, kind, group)  # type: ignore[arg-type]
            tools.append(tool)
            actions[tool["function"]["name"]] = {action.name: action for action in group}
    return AreaSurface(tools=tuple(tools), actions=actions)


__all__ = [
    "AREAS",
    "AREA_OF",
    "DO",
    "ENTRIES",
    "ENTRY_LINES",
    "FIND",
    "INTROS",
    "Area",
    "AreaCallError",
    "AreaEntry",
    "AreaSurface",
    "build_surface",
    "do_name",
    "find_name",
]
