"""The client assistant's second set of read tools: one object in detail, and the screens
the first set could not see (D-698).

`tools.READ_TOOLS` answers questions ABOUT a list — how many leads, which calls, which
agents. These answer what a person asks once they are looking at ONE thing ("what does
this agent say first?", "what happened on this call?") and what the actions in
`console_actions.py` need before they can be planned: ids. Every row names its object by
id so the model can act on it without asking the person to copy one.

THE SAME FOUR RULES AS `tools.py`, BECAUSE THESE ARE THE SAME KIND OF TOOL:

1. Each executor calls the function the console screen serving the same data calls —
   `roster.agent_by_id`, `crm_service.get_call(raw=False)`, `campaign_progress`,
   `read_wallet`, `attention_queue` — and, where the screen's route holds its own query
   (the numbers list, the webhook list, the team, the voice picker), the ROUTE FUNCTION
   itself rather than a copy of its SQL.
2. The permission is the screen's, checked by `tools.run_read_tool` before anything runs.
   Where one result mixes two screens (the wallet is `wallet:read`, statements
   `billing:read`) the second half is asked of the role inside the executor.
3. Text goes through `tools._clean` (redaction, then defusing) and IDS DO NOT: a uuid is
   not personal data, and a redactor that read a digit run inside one as a phone number
   would hand the model an id it cannot use. Ids are appended after the cleaned text.
4. Nothing here returns a raw transcript, a recording link, a full phone number or an
   extraction value. The raw transcript is `calls:read_raw` plus an audit row on its own
   screen (hard rule 5); a recording link is a short-lived credential and belongs in a
   browser, not a prompt.

Registered in `CONSOLE_READ_TOOLS` and composed after `tools.READ_TOOLS` by
`service.realm_read_tools`, so the earlier tools' positions in the cacheable prefix do not
move. New tools APPEND.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import roster
from apps.api.billing.rates import PREPAID_TIERS
from apps.api.billing.service import plan_tier_of
from apps.api.billing.wallet import read_wallet
from apps.api.callbacks import service as callbacks_service
from apps.api.campaigns import service as campaigns_service
from apps.api.compliance.kyc import kyc_not_verified_reason, read_kyc
from apps.api.compliance.kyc_documents import current_documents
from apps.api.compliance.outbound_pledge import pledge_blocker
from apps.api.compliance.service import credits_exhausted
from apps.api.copilot.tools import (
    MAX_ROWS,
    ReadTool,
    ToolContext,
    _cap,
    _clean,
    _listing,
    _nothing,
    ist_date,
    ist_stamp,
)
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import role_has
from apps.api.crm import service as crm_service
from apps.api.crm.attention import attention_queue, failed_deliveries
from apps.api.ingest.service import list_lead_sources
from apps.api.kb import service as kb_service
from apps.api.kb import uploads as kb_uploads
from apps.api.quality.service import list_reports

#: How many transcript turns `call_detail` hands the model, and how much of each. A call
#: summary answers most questions; the turns are for "what exactly did they ask", and a
#: forty-turn window is the whole of an ordinary booking call.
MAX_TURNS_SHOWN: Final = 40
MAX_TURN_CHARS: Final = 300

#: The statuses a call is in while somebody may still be on the line
#: (`crm/service.DAILY_CALL_CLASSES["in_flight"]`).
LIVE_CALL_STATUSES: Final = ("queued", "ringing", "in_progress")


def _uuid_arg(args: Mapping[str, Any], key: str) -> UUID | None:
    raw = args.get(key)
    if not isinstance(raw, str):
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


def _missing_id(key: str, where: str) -> str:
    return (
        f"`{key}` was missing or is not an id. Take it from the SCREEN STATE or from "
        f"{where}, and call this again."
    )


def _principal(context: ToolContext) -> Principal:
    """The narrow principal a ROUTE FUNCTION needs when this module calls it directly
    (`list_numbers`, `list_endpoints`, `list_members`, `list_voices`): the tenant and the
    role, nothing else."""
    return Principal(realm="client", user_id=None, tenant_id=context.tenant_id, role=context.role)


def _date(value: Any) -> str:
    return ist_date(value) if isinstance(value, datetime) else "—"


# --- agent_detail ----------------------------------------------------------------------


async def _agent_detail(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`roster.agent_by_id` — `GET /v1/agents/{id}`'s reader — plus whether a script edit
    is waiting to be put live (the two prompt pointers differ)."""
    del context
    agent_id = _uuid_arg(args, "agent_id")
    if agent_id is None:
        return _missing_id("agent_id", "an `agents_list` lookup")
    agent = await roster.agent_by_id(session, agent_id)
    if agent is None:
        return "No agent with that id in this account."
    staged = (
        await session.execute(
            text(
                "SELECT system_prompt_id IS DISTINCT FROM live_prompt_id "
                "AND live_prompt_id IS NOT NULL FROM agents WHERE id = :aid"
            ),
            {"aid": agent_id},
        )
    ).scalar()
    fields = ", ".join(f"{field.label} ({field.key})" for field in agent.extraction_fields)
    lines = [
        f"Agent {agent.name}: {agent.direction}, {agent.status}, "
        + ("published to the phone system" if agent.published else "not published yet")
        + f", speaks {agent.language_primary}, {agent.inbound_number_count} number(s).",
        f"Voice: {agent.engine_voice_id or 'the platform default'}. "
        f"Model tier: {agent.llm_tier_label}.",
        "Opening notices: AI disclosure "
        + ("ON" if agent.ai_disclosure_enabled else "off")
        + ", recording notice "
        + ("ON" if agent.recording_notice_enabled else "off")
        + ". Whatever the toggles, the agent always answers truthfully if asked whether "
        "it is an AI or whether the call is recorded.",
        # The notices and the opening line are separate things (D-708): the switches above
        # decide only whether the notices come before the opening line.
        "Its opening line (the greeting, from its script): "
        + (agent.script_opening_line or "none written yet")
        + ".",
        f"Callers hear first: {agent.first_words or 'nothing yet'}",
        f"It captures: {fields}." if fields else "It captures no custom fields yet.",
    ]
    if staged:
        lines.append(
            "A script change is saved but NOT live yet: callers still hear the previous "
            "script until it is applied (`agent_changes_apply`)."
        )
    return _clean("\n".join(lines)) + f"\n[agent_id {agent_id}]"


# --- lead_detail -----------------------------------------------------------------------


async def _lead_detail(session: AsyncSession, context: ToolContext, args: Mapping[str, Any]) -> str:
    """`crm_service.get_lead` and `lead_timeline` — the lead screen's two reads.

    The captured FIELD NAMES are listed, never their values: `data` is the extraction
    payload hard rule 6 names beside transcripts, and the lead's own screen is where a
    person reads it.
    """
    del context
    lead_id = _uuid_arg(args, "lead_id")
    if lead_id is None:
        return _missing_id("lead_id", "a `leads_search` lookup")
    try:
        lead = await crm_service.get_lead(session, lead_id)
    except ProblemError:
        return "No lead with that id in this account."
    timeline = await crm_service.lead_timeline(session, lead_id, limit=10)
    captured = sorted(key for key, value in lead.data.items() if value not in (None, "", []))
    head = (
        f"Lead {lead.name or 'unnamed'} · {lead.status} · from {lead.source} · "
        f"{lead.call_count} call(s)"
        + (" · repeat caller" if lead.is_repeat_caller else "")
        + f" · phone {lead.phone_e164}"
        + (" · has an owner" if lead.assigned_to else " · nobody owns it")
        + f" · added {_date(lead.created_at)}"
    )
    lines = [head]
    lines.append(
        "Captured fields: " + ", ".join(captured) + " (values are on the lead's screen)."
        if captured
        else "Nothing captured on this lead yet."
    )
    if timeline.items:
        lines.append(f"Latest of {timeline.total} event(s):")
        lines.extend(
            f"- {_date(item.occurred_at)} {item.title}"
            + (f" — {item.detail[:120]}" if item.detail else "")
            for item in timeline.items
        )
    return _clean("\n".join(lines)) + f"\n[lead_id {lead_id}]"


# --- call_detail -----------------------------------------------------------------------


async def _call_detail(session: AsyncSession, context: ToolContext, args: Mapping[str, Any]) -> str:
    """`crm_service.get_call(raw=False)` — `GET /v1/calls/{id}`, the REDACTED read. The raw
    transcript is never fetched here: it is `calls:read_raw` plus an audit row, on the
    call's own screen (hard rule 5)."""
    del context
    call_id = _uuid_arg(args, "call_id")
    if call_id is None:
        return _missing_id("call_id", "a `calls_recent` lookup")
    try:
        call = await crm_service.get_call(session, call_id, raw=False)
    except ProblemError:
        return "No call with that id in this account."
    try:
        await crm_service.recording_ref_for(session, call_id)
        recording = (
            "A recording exists; it plays on this call's screen under Call logs, for "
            "people allowed to hear recordings."
        )
    except ProblemError:
        recording = "There is no recording of this call."
    lines = [
        f"Call on {_date(call.started_at)}, {call.direction}, {call.status}"
        + (f", {call.duration_s}s" if call.duration_s is not None else "")
        + (f", agent {call.agent_name}" if call.agent_name else "")
        + (f", outcome {call.outcome_tag}" if call.outcome_tag else "")
        + (f", sentiment {call.sentiment}" if call.sentiment else "")
        + ".",
        f"Summary: {call.summary}" if call.summary else "No summary yet.",
        recording,
    ]
    turns = call.transcript[:MAX_TURNS_SHOWN]
    if turns:
        lines.append(f"Transcript (redacted; first {len(turns)} of {len(call.transcript)} turns):")
        lines.extend(f"{turn.speaker}: {turn.text[:MAX_TURN_CHARS]}" for turn in turns)
    else:
        lines.append("No transcript is stored for this call.")
    suffix = f"\n[call_id {call_id}]"
    if call.lead_id is not None:
        suffix += f" [lead_id {call.lead_id}]"
    return _clean("\n".join(lines)) + suffix


# --- calls_live ------------------------------------------------------------------------


async def _calls_live(session: AsyncSession, context: ToolContext, args: Mapping[str, Any]) -> str:
    """`crm_service.list_calls`, once per in-flight status — the reader the Call logs
    screen filters with."""
    del context, args
    rows = []
    for status in LIVE_CALL_STATUSES:
        rows.extend(await crm_service.list_calls(session, limit=MAX_ROWS, status=status))
    if not rows:
        return "No call is in progress right now."
    lines = [
        _clean(
            f"- {call.direction} · {call.status}"
            + (f" · agent {call.agent_name}" if call.agent_name else "")
        )
        + f" [call_id {call.id}]"
        for call in rows[:MAX_ROWS]
    ]
    return _listing(lines, shown_of="calls in progress", nothing="No call is in progress.")


# --- callbacks_list --------------------------------------------------------------------


async def _callbacks_list(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`callbacks_service.list_callbacks` — `GET /v1/callbacks`."""
    del context
    open_only = bool(args.get("open_only"))
    rows = await callbacks_service.list_callbacks(
        session, limit=_cap(args.get("limit"), default=MAX_ROWS), open_only=open_only
    )
    lines = [
        _clean(
            f"- {row['status']} · due {ist_stamp(row['requested_at'])} · "
            f"{row['attempts']} attempt(s)"
            + (f" · last refused: {row['last_refusal_rule']}" if row["last_refusal_rule"] else "")
        )
        + f" [callback_id {row['id']}]"
        + (f" [lead_id {row['lead_id']}]" if row["lead_id"] else "")
        for row in rows
    ]
    return _listing(
        lines,
        shown_of="call-backs",
        nothing=_nothing(
            "call-backs",
            matching="still waiting" if open_only else None,
            next_step="A call-back is booked when a caller asks to be called back.",
        ),
    )


# --- knowledge_sources -----------------------------------------------------------------


async def _knowledge_sources(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`kb_service.list_sources` and `kb_uploads.list_uploads` — the Knowledge base
    screen's two lists. A document or a link carries the `upload_id` its Remove button
    uses; typed facts have no remove button and so no id to remove by."""
    del context, args
    sources = await kb_service.list_sources(session, limit=MAX_ROWS)
    uploads = {
        str(row["source_id"]): row for row in await kb_uploads.list_uploads(session, limit=MAX_ROWS)
    }
    lines = []
    for source in sources:
        upload = uploads.get(str(source["id"]))
        line = _clean(
            f"- {source['name']} · {source['kind']} · {source['status']}"
            + (" · live" if source["is_active"] else " · not live")
            + f" · version {source['version']}"
        )
        if upload is not None:
            line += f" [upload_id {upload['id']}]"
        lines.append(line)
    return _listing(
        lines,
        shown_of="knowledge sources",
        nothing=_nothing(
            "knowledge",
            next_step="Facts, documents and web pages are added on the Knowledge base screen.",
        ),
    )


# --- numbers_list ----------------------------------------------------------------------


async def _numbers_list(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """The phone-number screen's own route function, `campaigns.routes.list_numbers`,
    called directly rather than copying its query; plus `purchase_readiness`, which says
    whether a new number can be bought and at what monthly price."""
    del args
    from apps.api.campaigns.engine_number_purchase import purchase_readiness
    from apps.api.campaigns.routes import list_numbers
    from apps.api.tenancy.engine_workspace import engine_has_workspaces

    assert context.tenant_id is not None
    numbers = await list_numbers(session, _principal(context))
    lines = []
    for number in numbers:
        dumped = number.model_dump()
        lines.append(
            _clean(
                f"- {dumped.get('e164')} · {dumped.get('direction') or 'no direction'}"
                + (" · answers calls" if dumped.get("answerable") else "")
                + (
                    f" · ₹{dumped['inr_per_month']}/month"
                    if dumped.get("inr_per_month") is not None
                    else ""
                )
            )
            + f" [number_id {dumped.get('id')}]"
            + (f" [agent_id {dumped['agent_id']}]" if dumped.get("agent_id") else "")
        )
    body = _listing(
        lines,
        shown_of="numbers",
        nothing=_nothing(
            "phone numbers", next_step="One is bought on the Your phone number screen."
        ),
    )
    if engine_has_workspaces():
        readiness = await purchase_readiness(session, tenant_id=context.tenant_id)
        if readiness.step == "ready":
            price = readiness.client_inr_per_month
            body += (
                "\nA new number can be bought"
                + (f" at ₹{price} a month" if price is not None else "")
                + " (`number_buy`)."
            )
        else:
            body += (
                f"\nA new number cannot be bought yet: {readiness.blocker or readiness.step}. "
                "The Your phone number screen walks through it."
            )
    return body


async def _numbers_available(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`engine_numbers.available_cities` / `search_available` — the buy panel's reads.
    The numbers are masked by `_clean`; `number_buy` picks one itself, by city."""
    from apps.api.campaigns import engine_numbers
    from apps.api.tenancy.engine_workspace import engine_has_workspaces

    assert context.tenant_id is not None
    if not engine_has_workspaces():
        return "Numbers are not bought in the app on this account's phone system."
    city = args.get("city")
    if not isinstance(city, str) or not city.strip():
        cities = await engine_numbers.available_cities(session, context.tenant_id)
        return _clean(
            "Cities with numbers available: "
            + ", ".join(f"{c.name} ({c.available})" for c in cities[:MAX_ROWS])
            if cities
            else "No numbers are available in any city right now."
        )
    named = city.strip()[:60]
    page = await engine_numbers.search_available(
        session, context.tenant_id, city=named, pattern=None, cursor=None
    )
    if not page.numbers:
        return _clean(f"No numbers are available in {named} right now.")
    return _clean(
        f"{len(page.numbers)} number(s) available in {named}, e.g. "
        + ", ".join(str(n.number) for n in page.numbers[:5])
        + ". `number_buy` with this city takes the first one available when the person "
        "confirms."
    )


# --- billing_overview ------------------------------------------------------------------


async def _billing_overview(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`read_wallet` exactly as `GET /v1/billing/wallet` builds it, and — for a role that
    holds `billing:read` — recent statements. The assistant never takes payment: the
    answer points at the screen where a person adds credit."""
    del args
    assert context.tenant_id is not None
    tier = await plan_tier_of(session, context.tenant_id)
    stopped = await credits_exhausted(session, tenant_id=context.tenant_id)
    wallet = await read_wallet(
        session,
        tenant_id=context.tenant_id,
        prepaid=tier in PREPAID_TIERS,
        outbound_stopped=stopped,
    )
    lines = []
    if wallet.prepaid:
        lines.append(f"Credit balance: ₹{wallet.balance.amount_inr}.")
        runway = wallet.runway
        days = getattr(runway, "days", None)
        lines.append(
            f"At the recent rate of use that lasts about {days} day(s)."
            if days is not None
            else f"How long it lasts cannot be projected yet ({runway.basis})."
        )
    else:
        lines.append("This account is invoiced; it has no prepaid credit balance.")
    lines.append(
        "Outbound calling is STOPPED for lack of credit."
        if wallet.outbound_stopped
        else "Outbound calling is not stopped by credit."
    )
    if context.role is not None and role_has(context.role, "billing:read"):
        from apps.api.billing.history import statement_page

        page = await statement_page(session, tenant_id=context.tenant_id, limit=3, before=None)
        lines.append(
            f"{len(page.statements)} recent statement(s) are under the Statements tab."
            if page.statements
            else "No statements yet."
        )
    lines.append(
        "To add credit: the Credits & billing screen, Add credit tab. The assistant cannot "
        "take a payment."
    )
    return _clean(" ".join(lines))


# --- verification_status ---------------------------------------------------------------


async def _verification_status(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """The Verify your business screen's reads — `read_kyc`, `current_documents` and
    `pledge_blocker` — plus the business profile's go-live list. The assistant explains
    and links; it never uploads a document or accepts the pledge (D-694)."""
    del args
    from apps.api.tenancy.business_profile import go_live_blockers, load_profile

    assert context.tenant_id is not None
    kyc = await read_kyc(session, tenant_id=context.tenant_id)
    documents = await current_documents(session, tenant_id=context.tenant_id)
    pledge = await pledge_blocker(session, tenant_id=context.tenant_id)
    lines = []
    if not kyc.recorded:
        lines.append("Business verification: not started.")
    elif kyc.is_verified:
        lines.append("Business verification: verified.")
    else:
        lines.append(
            f"Business verification: {kyc.status}. {kyc_not_verified_reason(str(kyc.status))}"
        )
        if kyc.rejection_reason:
            lines.append(f"Reviewer's note: {kyc.rejection_reason[:300]}")
    if kyc.digilocker_required and kyc.digilocker_verified_at is None:
        lines.append("A DigiLocker check is still required.")
    missing = []
    if kyc.legal_business_name is None or kyc.gst_registered is None:
        missing.append("the legal business name and GST status")
    if "business" not in documents:
        missing.append("the business registration document")
    if missing:
        lines.append("Still needed: " + "; ".join(missing) + ".")
    lines.append(
        "No-cold-calls pledge: accepted."
        if pledge is None
        else f"No-cold-calls pledge: not accepted ({pledge[0]}). Only the owner accepts it."
    )
    profile = await load_profile(session, tenant_id=context.tenant_id)
    blockers = go_live_blockers(profile)
    lines.append(
        "Business profile: ready for an agent to go live."
        if not blockers
        else "Business profile still needs: " + ", ".join(blockers) + "."
    )
    lines.append(
        "Documents are uploaded and the pledge is accepted by the person on the Verify "
        "your business screen; the business profile is on the Business profile screen. "
        "The assistant cannot upload documents or accept anything for them."
    )
    return _clean("\n".join(lines))


# --- integrations_status ---------------------------------------------------------------


async def _integrations_status(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`list_lead_sources`, `failed_deliveries` and the Integrations screen's own
    `list_endpoints` route function. Endpoint addresses are reduced to their host."""
    del args
    from urllib.parse import urlsplit

    from apps.api.integrations.routes import list_endpoints

    sources = await list_lead_sources(session, limit=MAX_ROWS)
    endpoints = await list_endpoints(session, 50, _principal(context))
    failures = await failed_deliveries(session, limit=5)
    source_line = f"Lead sources: {len(sources)}"
    if sources:
        source_line += (
            " (" + ", ".join(f"{s.source} {'on' if s.active else 'off'}" for s in sources) + ")"
        )
    endpoint_line = f"Outbound connections: {len(endpoints)}"
    if endpoints:
        endpoint_line += (
            " ("
            + ", ".join(
                f"{e.kind} to {urlsplit(str(e.url)).hostname or 'a sheet'} "
                + ("on" if e.active else "off")
                for e in endpoints[:10]
            )
            + ")"
        )
    failure_line = f"Deliveries that did not arrive recently: {failures.total}."
    if failures.items:
        failure_line += " Latest: " + "; ".join(item.title for item in failures.items[:3])
    lines = [
        source_line + ".",
        endpoint_line + ".",
        failure_line,
        "Connecting a new source or destination is done on the Lead sources and "
        "Integrations screens, which show the address and secret to copy.",
    ]
    return _clean("\n".join(lines))


# --- needs_attention -------------------------------------------------------------------


async def _needs_attention(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`attention_queue` — the Needs attention screen's read."""
    del context
    queue = await attention_queue(session, limit=_cap(args.get("limit"), default=10))
    if not queue["items"]:
        return "Nothing needs attention right now."
    counts = ", ".join(f"{kind} {count}" for kind, count in queue["counts"].items())
    lines = [f"{queue['total']} thing(s) need attention ({counts}):"]
    lines.extend(
        _clean(f"- {item['kind']}: {item['title']} — {item['detail']}")
        + (f" [{item['kind']}_id {item['id']}]" if item.get("id") else "")
        for item in queue["items"]
    )
    return "\n".join(lines)


# --- quality_reports -------------------------------------------------------------------


async def _quality_reports(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`quality.service.list_reports` — the Quality screen's read. Built from scripted
    test scenarios, never from a real call."""
    del context, args
    reports = await list_reports(session, limit=3)
    if not reports:
        return (
            "No quality check has been run for this account yet — that is not the same as "
            "a clean result."
        )
    lines = ["Quality checks (scripted test calls, not real ones), newest first:"]
    for report in reports:
        lines.append(
            f"- {report.as_of.isoformat()}: {report.scenarios_total} scenario(s), "
            f"{report.defects} defect(s), {report.red_team} adversarial check(s), "
            f"trend {report.trend}"
        )
    return _clean("\n".join(lines))


# --- campaign_detail -------------------------------------------------------------------


async def _campaign_detail(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`campaign_progress` — `GET /v1/campaigns/{id}` — and, before a launch,
    `launch_blockers`, the gate the launch button asks."""
    campaign_id = _uuid_arg(args, "campaign_id")
    if campaign_id is None:
        return _missing_id("campaign_id", "a `campaigns_list` lookup")
    assert context.tenant_id is not None
    try:
        progress = await campaigns_service.campaign_progress(session, campaign_id)
    except ProblemError:
        return "No campaign with that id in this account."
    counts = ", ".join(f"{k} {v}" for k, v in progress["contacts"].items()) or "no contacts yet"
    lines = [f"Status {progress['status']}; {progress['total']} contact(s) ({counts})."]
    if progress["scheduled_start_at"]:
        lines.append(f"Scheduled to start {ist_stamp(progress['scheduled_start_at'])}.")
    if progress["recurrence"]:
        lines.append(f"Repeats: {progress['recurrence']}.")
    if progress["calling_hours"]:
        hours = progress["calling_hours"]
        lines.append(f"Calls only between {hours['start']} and {hours['end']} IST.")
    if progress["status"] in ("draft", "scheduled"):
        blockers = await campaigns_service.launch_blockers(
            session, tenant_id=context.tenant_id, campaign_id=campaign_id
        )
        lines.append(
            "Ready to launch."
            if not blockers
            else "Cannot launch yet: " + "; ".join(f"{b.rule}: {b.reason}" for b in blockers)
        )
    return _clean("\n".join(lines)) + f"\n[campaign_id {campaign_id}]"


# --- team_members ----------------------------------------------------------------------


async def _team_members(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """The team picker's own route function, `tenancy.routes.list_members` — ids, display
    names and roles, never emails. `lead_assign` takes one of these ids."""
    del args
    from apps.api.tenancy.routes import list_members

    members = await list_members(session, MAX_ROWS, _principal(context))
    lines = [
        _clean(f"- {member.name or 'unnamed'} · {member.role}") + f" [user_id {member.id}]"
        for member in members
    ]
    return _listing(lines, shown_of="team members", nothing="This account has no team members.")


# --- voices_offered --------------------------------------------------------------------


async def _voices_offered(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """The voice picker's own route function, `agents.voice_routes.list_voices` — so the
    assistant offers exactly the voices the picker offers and `set_agent_voice` accepts."""
    del session, args
    from apps.api.agents.voice_routes import list_voices

    catalogue = await list_voices(_principal(context))
    rows = [voice for voice in catalogue.voices if voice.offerable][:MAX_ROWS]
    if not rows:
        return _clean(catalogue.note or "No voice can be chosen on this account right now.")
    lines = [
        _clean(f"- {voice.label} · {voice.tier_label}") + f" [voice_id {voice.id}]"
        for voice in rows
    ]
    return _listing(lines, shown_of="voices", nothing="No voice can be chosen right now.")


# --- the registry ----------------------------------------------------------------------


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _id_param(key: str, where: str) -> dict[str, Any]:
    description = f"The {where}'s id, from the SCREEN STATE or a lookup."
    return {key: {"type": "string", "description": description}}


_LIMIT: Final = {
    "anyOf": [{"type": "integer"}, {"type": "null"}],
    "description": f"How many to return, at most {MAX_ROWS}. Null means {MAX_ROWS}.",
}

#: Registration order is wire order. New tools APPEND.
CONSOLE_READ_TOOLS: Final[tuple[ReadTool, ...]] = (
    ReadTool(
        name="agent_detail",
        description=(
            "One voice agent in detail: its status, language, voice, model tier, whether "
            "its opening AI-disclosure and recording notices are on, the opening line it "
            "says, the fields it captures, and whether a saved script change is still "
            "waiting to go live."
        ),
        parameters=_object(_id_param("agent_id", "agent")),
        permission="agents:read",
        run=_agent_detail,
    ),
    ReadTool(
        name="lead_detail",
        description=(
            "One lead in detail: status, source, call count, whether someone owns it, "
            "which fields have been captured (names only), and its latest history."
        ),
        parameters=_object(_id_param("lead_id", "lead")),
        permission="leads:read",
        run=_lead_detail,
    ),
    ReadTool(
        name="call_detail",
        description=(
            "One call in detail: when, direction, outcome, its summary, whether a "
            "recording exists, and its REDACTED transcript (names and numbers removed). "
            "The unredacted transcript and the recording itself are only on the call's "
            "own screen."
        ),
        parameters=_object(_id_param("call_id", "call")),
        permission="calls:read",
        run=_call_detail,
    ),
    ReadTool(
        name="calls_live",
        description="The calls in progress right now (queued, ringing or connected).",
        parameters=_object({}),
        permission="calls:read",
        run=_calls_live,
    ),
    ReadTool(
        name="callbacks_list",
        description=(
            "This account's call-backs — calls a caller asked for and the platform will "
            "place: when each is due, its state, attempts and why the last one was refused."
        ),
        parameters=_object(
            {
                "open_only": {
                    "anyOf": [{"type": "boolean"}, {"type": "null"}],
                    "description": "True for only the ones still waiting. Null means all.",
                },
                "limit": _LIMIT,
            }
        ),
        permission="leads:read",
        run=_callbacks_list,
    ),
    ReadTool(
        name="knowledge_sources",
        description=(
            "Everything in this account's knowledge base — typed facts, documents and web "
            "pages — with whether each is live, waiting for review or rejected."
        ),
        parameters=_object({}),
        permission="agents:read",
        run=_knowledge_sources,
    ),
    ReadTool(
        name="numbers_list",
        description=(
            "This account's phone numbers (masked), which agent each belongs to, whether "
            "it answers calls and its monthly price, and whether a new number can be bought."
        ),
        parameters=_object({}),
        permission="org:read",
        run=_numbers_list,
    ),
    ReadTool(
        name="numbers_available",
        description=(
            "Phone numbers available to buy. With a null city it lists the cities that "
            "have numbers; with a city it says how many are available there."
        ),
        parameters=_object(
            {
                "city": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "A city name from the city list, or null for the list.",
                }
            }
        ),
        permission="org:read",
        run=_numbers_available,
    ),
    ReadTool(
        name="billing_overview",
        description=(
            "The account's credit balance, how long it lasts, whether outbound calling is "
            "stopped for credit, recent statements, and where to add credit. The assistant "
            "never takes payments."
        ),
        parameters=_object({}),
        permission="wallet:read",
        run=_billing_overview,
    ),
    ReadTool(
        name="verification_status",
        description=(
            "Where the account stands on business verification (KYC), what is still "
            "needed, whether the no-cold-calls pledge is accepted, and what the business "
            "profile still needs before an agent can go live — with the screen to do each."
        ),
        parameters=_object({}),
        permission="org:read",
        run=_verification_status,
    ),
    ReadTool(
        name="integrations_status",
        description=(
            "The account's lead sources, its outbound connections (webhooks and "
            "spreadsheets) and any deliveries that failed recently, with where to set them up."
        ),
        parameters=_object({}),
        permission="org:read",
        run=_integrations_status,
    ),
    ReadTool(
        name="needs_attention",
        description=(
            "What needs attention right now: blocked leads, failed deliveries, stalled "
            "campaigns, knowledge waiting and inbound lines that stopped answering."
        ),
        parameters=_object({"limit": _LIMIT}),
        permission="leads:read",
        run=_needs_attention,
    ),
    ReadTool(
        name="quality_reports",
        description=(
            "The latest quality checks run on this account's agents with scripted test "
            "calls: scenarios, defects found and the trend."
        ),
        parameters=_object({}),
        permission="agents:read",
        run=_quality_reports,
    ),
    ReadTool(
        name="campaign_detail",
        description=(
            "One campaign in detail: status, contacts by state, schedule, calling hours, "
            "and — before launch — exactly what still blocks it."
        ),
        parameters=_object(_id_param("campaign_id", "campaign")),
        permission="leads:read",
        run=_campaign_detail,
    ),
    ReadTool(
        name="team_members",
        description=(
            "The people on this account's team, with their role and the id `lead_assign` "
            "takes. Names only — never emails."
        ),
        parameters=_object({}),
        permission="org:read",
        run=_team_members,
    ),
    ReadTool(
        name="voices_offered",
        description=(
            "The voices an agent can be switched to on this account right now, with the "
            "id `agent_edit` takes."
        ),
        parameters=_object({}),
        permission="agents:read",
        run=_voices_offered,
    ),
)

CONSOLE_READ_TOOL_NAMES: Final[frozenset[str]] = frozenset(t.name for t in CONSOLE_READ_TOOLS)

__all__ = ["CONSOLE_READ_TOOLS", "CONSOLE_READ_TOOL_NAMES"]
