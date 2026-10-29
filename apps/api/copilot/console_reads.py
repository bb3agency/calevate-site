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
3. Text goes through `tools._clean` (redaction unless the account turned Pip on, then
   defusing) and IDS DO NOT: a uuid is
   not personal data, and a redactor that read a digit run inside one as a phone number
   would hand the model an id it cannot use. Ids are appended after the cleaned text.
4. Before consent nothing here returns a raw transcript, a full phone number or an
   extraction value; after it (D-788) `call_detail` returns the raw transcript with the
   audit row hard rule 5 requires, and `lead_detail` the captured values. A recording link
   is never returned: it is a short-lived credential and belongs in a browser, not a
   prompt.

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

from apps.api.agents import roster, voice_tuning
from apps.api.billing.display import display_decimal, display_inr
from apps.api.billing.rates import PREPAID_TIERS
from apps.api.billing.service import plan_tier_of
from apps.api.billing.wallet import read_wallet
from apps.api.callbacks import service as callbacks_service
from apps.api.campaigns import results as campaign_results
from apps.api.campaigns import service as campaigns_service
from apps.api.compliance.audit import write_audit
from apps.api.compliance.kyc import kyc_not_verified_reason, read_kyc
from apps.api.compliance.kyc_documents import current_documents
from apps.api.compliance.outbound_pledge import pledge_blocker
from apps.api.compliance.service import credits_exhausted
from apps.api.copilot.agent_reads import AGENT_SETTINGS_READ
from apps.api.copilot.knowledge_reads import KNOWLEDGE_SOURCES
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
from apps.api.core.rbac import ADMIN_ROLES, role_has
from apps.api.crm import service as crm_service
from apps.api.crm.attention import attention_queue, failed_deliveries
from apps.api.ingest.service import list_lead_sources
from apps.api.quality.service import list_reports
from apps.api.teach import questions as teach_questions

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


def _captured(value: Any) -> str:
    """One captured value as a short line: a list joined, anything long cut at 200."""
    shown = ", ".join(str(item) for item in value) if isinstance(value, list) else str(value)
    return shown[:200]


# --- agent_detail ----------------------------------------------------------------------


async def _agent_detail(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`roster.agent_by_id` — `GET /v1/agents/{id}`'s reader — plus whether a script edit
    is waiting to be put live (the two prompt pointers differ). An operator also reads how
    the agent's Studio voice is tuned (the admin agent screen's "How it sounds"), which a
    client never sees."""
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
        # decide only whether the notices follow the opening line (D-861).
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
    if context.role in ADMIN_ROLES:
        lines.append(await _voice_tuning_line(session, agent_id))
    return _clean("\n".join(lines)) + f"\n[agent_id {agent_id}]"


async def _voice_tuning_line(session: AsyncSession, agent_id: UUID) -> str:
    state = await voice_tuning.read_voice_tuning(session, agent_id)
    if not state.studio:
        return "How it sounds: not a Studio voice, so no speed, volume or emotion settings."
    tuning = state.tuning
    held = [
        f"{name} {value}"
        for name, value in (
            ("speed", tuning.speed),
            ("volume", tuning.volume),
            ("emotion", tuning.emotion),
            ("voice model", tuning.model),
            ("pronunciation dictionary", tuning.dictionary_id),
        )
        if value is not None
    ]
    return "How it sounds (Studio voice, operators only): " + (
        ", ".join(held) + "." if held else "the voice's own defaults."
    )


# --- lead_detail -----------------------------------------------------------------------


async def _lead_detail(session: AsyncSession, context: ToolContext, args: Mapping[str, Any]) -> str:
    """`crm_service.get_lead` and `lead_timeline` — the lead screen's two reads.

    The captured values are listed when the account turned Pip on (D-788): they are the
    lead's details the person is asking Pip about. Otherwise only the field NAMES are, and
    the lead's own screen is where a person reads the values.
    """
    lead_id = _uuid_arg(args, "lead_id")
    if lead_id is None:
        return _missing_id("lead_id", "a `leads_search` lookup")
    try:
        lead = await crm_service.get_lead(session, lead_id)
    except ProblemError:
        return "No lead with that id in this account."
    timeline = await crm_service.lead_timeline(session, lead_id, limit=10)
    captured = sorted(key for key, value in lead.data.items() if value not in (None, "", []))
    unmasked = context.unmasked is not None
    head = (
        f"Lead {lead.name or 'unnamed'} · {lead.status} · from {lead.source} · "
        f"{lead.call_count} call(s)"
        + (" · repeat caller" if lead.is_repeat_caller else "")
        + f" · phone {lead.phone_e164}"
        + (" · has an owner" if lead.assigned_to else " · nobody owns it")
        + f" · added {_date(lead.created_at)}"
    )
    lines = [head]
    if not captured:
        lines.append("Nothing captured on this lead yet.")
    elif unmasked:
        lines.append(
            "Captured: " + "; ".join(f"{key}: {_captured(lead.data[key])}" for key in captured)
        )
    else:
        lines.append(
            "Captured fields: " + ", ".join(captured) + " (values are on the lead's screen)."
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
    """`crm_service.get_call` — the call screen's read.

    RAW when the account turned Pip on (D-788): the transcript and summary as spoken, with
    the `transcript.read_raw` audit row `GET /v1/calls/{id}/transcript/raw` writes, in the
    same transaction as the read (hard rule 5). Otherwise the REDACTED read,
    `GET /v1/calls/{id}`. The tool itself needs `calls:read`; the RAW read also needs
    `calls:read_raw`, the permission the raw route asks. Consent decides whether Pip may
    see unmasked text at all, never who may: without this a `staff` member, who holds
    `calls:read` only, would read through Pip the transcript the raw route refuses them."""
    call_id = _uuid_arg(args, "call_id")
    if call_id is None:
        return _missing_id("call_id", "a `calls_recent` lookup")
    may_read_raw = context.role is not None and role_has(context.role, "calls:read_raw")
    raw = context.unmasked if may_read_raw else None
    try:
        call = await crm_service.get_call(session, call_id, raw=raw is not None)
    except ProblemError:
        return "No call with that id in this account."
    if raw is not None:
        await write_audit(
            session,
            action="transcript.read_raw",
            actor=raw.actor,
            tenant_id=context.tenant_id,
            object_type="call",
            object_id=str(call_id),
            ip=raw.ip,
            summary={"via": "copilot"},
        )
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
        shown = "" if raw is not None else "redacted; "
        lines.append(f"Transcript ({shown}first {len(turns)} of {len(call.transcript)} turns):")
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
            + (
                # D-914: held while its campaign is paused, called off when it stopped.
                f" · {callbacks_service.CAMPAIGN_PAUSED_REASON}"
                if row["held"]
                else f" · {row['last_refusal_reason']}"
                if row["last_refusal_rule"] == callbacks_service.CAMPAIGN_STOPPED_RULE
                else f" · last refused: {row['last_refusal_rule']}"
                if row["last_refusal_rule"]
                else ""
            )
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


# --- knowledge_questions ---------------------------------------------------------------


_WHY_WORDS: Final = {
    "callers": "asked on {n} call(s)",
    "practice": "practice callers need it",
    "setup": "your setup leaves it open",
}


async def _knowledge_questions(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`teach.questions.list_questions`, the Questions to answer list. It never queues a
    draft: a question asked of Pip is not the owner opening the list."""
    if context.tenant_id is None:
        return "No account is open."
    found = await teach_questions.list_questions(
        session, tenant_id=context.tenant_id, agent_id=_uuid_arg(args, "agent_id")
    )
    lines = []
    for q in found.items[:MAX_ROWS]:
        line = f"- {q.question} · {_WHY_WORDS[q.why].format(n=q.callers)}"
        if q.draft:
            line += f" · draft from {q.draft_source_label}: {q.draft}"
        lines.append(_clean(line) + f" [question_key {q.key}]")
    return _listing(
        lines,
        total=found.open_count,
        shown_of="questions to answer",
        nothing="Nothing to answer: no caller, practice caller or setup step is waiting on one.",
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
                    f" · {display_inr(dumped['inr_per_month'])}/month"
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
                + (f" at {display_inr(price)} a month" if price is not None else "")
                + " (`number_buy`)."
            )
        else:
            body += (
                f"\nA new number cannot be bought yet: {readiness.blocker or readiness.step}. "
                "The Your phone number screen walks through it."
            )
    return body + await _forwarding_and_lines(session, context.tenant_id)


async def _forwarding_and_lines(session: AsyncSession, tenant_id: UUID) -> str:
    """The Phone numbers screen's other two reads: the business's existing numbers
    forwarded to Calevate (`forwarding.service.list_lines`) and the calls it may have at
    once (`tenancy.call_lines`), which only Calevate changes."""
    from apps.api.forwarding.service import list_lines
    from apps.api.healer.protection import fallback_phone
    from apps.api.tenancy.call_lines import calls_in_progress, read_call_lines

    lines = await list_lines(session)
    out = [
        "Existing numbers forwarded to Calevate:" if lines else "No existing number is forwarded."
    ]
    out.extend(
        _clean(
            f"- {line.e164} · {line.carrier} {line.line_kind} · "
            + (
                "every call"
                if line.mode == "all_calls"
                else f"when unanswered after {line.ring_seconds}s"
            )
            + f" · {line.status}"
        )
        + f" [line_id {line.id}]"
        for line in lines
    )
    state = await read_call_lines(session, tenant_id=tenant_id)
    busy = await calls_in_progress(session, tenant_id=tenant_id)
    out.append(
        f"Calls at once: {state.lines} ({busy} in progress). Only Calevate changes this; "
        "the person asks support for more."
    )
    backup = await fallback_phone(session)
    out.append(
        _clean(f"Backup phone when the agent cannot take calls: {backup}.")
        if backup
        else "No backup phone is set for when the agent cannot take calls."
    )
    return "\n" + "\n".join(out)


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
        lines.append(f"Credit balance: {display_inr(wallet.balance.amount_inr)}.")
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
    """The Lead sources and Integrations screens' reads: `list_lead_sources`, the
    lead-calling plan and its held leads (`ingest.lead_policy`), the endpoint list route
    function, `failed_deliveries`, and whether a Google account is connected for Sheets.
    Endpoint addresses are reduced to their host; secrets are never read."""
    del args
    from urllib.parse import urlsplit

    from apps.api.actions.credentials import list_credentials
    from apps.api.ingest import lead_policy
    from apps.api.integrations.routes import list_endpoints

    sources = await list_lead_sources(session, limit=MAX_ROWS)
    lines = [f"Lead sources: {len(sources)}."]
    lines.extend(
        _clean(f"- {s.source} · {'on' if s.active else 'paused'}")
        + f" [lead_source_id {s.id}]"
        + (f" [agent_id {s.agent_id}]" if s.agent_id else " (no agent chosen)")
        for s in sources
    )
    plan = await lead_policy.load_plan(session)
    lines.append(
        f"New leads are called {plan.hours_start:%H:%M}-{plan.hours_end:%H:%M} IST on "
        f"{','.join(plan.days)}, after a {plan.wait_seconds}s wait; after hours: "
        f"{plan.after_hours}; {plan.retry_attempts} retr(ies) every "
        f"{plan.retry_interval_minutes} min; answering machines "
        + ("detected" if plan.detect_machines else "not detected")
        + (
            f"; one agent calls them all [agent_id {plan.calling_agent_id}]."
            if plan.calling_agent_id
            else "; each source's own agent calls."
        )
    )
    held = await lead_policy.list_held(session, limit=10)
    if held:
        lines.append(f"Leads held after hours, waiting for a decision: {len(held)}.")
        lines.extend(
            f"- held {_date(h.held_at)} from {h.source} [hold_id {h.id}] [lead_id {h.lead_id}]"
            for h in held
        )
    endpoints = await list_endpoints(session, 50, _principal(context))
    lines.append(f"Outbound connections: {len(endpoints)}.")
    lines.extend(
        _clean(
            f"- {e.kind} to {urlsplit(str(e.url)).hostname if e.url else 'a sheet'} · "
            + ("on" if e.active else "off")
            + " · "
            + ", ".join(e.events)
        )
        + f" [endpoint_id {e.id}]"
        for e in endpoints[:10]
    )
    connected = await list_credentials(session)
    google = [c for c in connected if c.kind == "google_sheets"]
    lines.append(
        "Connected accounts: "
        + (
            "; ".join(
                _clean(f"{c.label} ({c.kind})") + f" [connection_id {c.id}]" for c in connected
            )
            or "none"
        )
        + "."
    )
    lines.append(
        "Google Sheets: connected."
        if google
        else "Google Sheets: not connected; the person connects Google on the Integrations "
        "screen themselves."
    )
    failures = await failed_deliveries(session, limit=5)
    lines.append(f"Deliveries that did not arrive recently: {failures.total}.")
    lines.extend(
        _clean(f"- {item.title}") + f" [delivery_id {item.id}]" for item in failures.items[:5]
    )
    lines.append(
        "A new source's address and secret, and a new endpoint's secret, are shown once to "
        "the person who confirms; Meta Lead Ads is set up on the Lead sources screen."
    )
    return "\n".join(lines)


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
    if progress["pause_reason"]:
        lines.append(f"Paused because: {progress['pause_reason']}.")
        if progress["complaint_review_required"]:
            lines.append("Resume waits for the client to confirm they reviewed the opt-outs.")
    if progress["not_calling"]:
        lines.append(
            "Running but calling nobody: "
            + "; ".join(f"{b['rule']}: {b['reason']}" for b in progress["not_calling"])
        )
    if progress["status"] not in ("draft", "scheduled"):
        found = await campaign_results.summary(
            session, campaign_id=campaign_id, include_spend=False
        )
        outcomes = ", ".join(f"{k} {v}" for k, v in found["outcomes"].items() if v)
        lines.append(f"People by outcome: {outcomes or 'none yet'}.")
        if found["pickup_rate"] is not None:
            lines.append(
                f"Picked up {round(found['pickup_rate'] * 100)}% of the {found['tried']} tried; "
                f"average connected call {found['average_call_s'] or 0}s."
            )
        lines.append(
            f"Calls placed {found['calls']} (call-backs included), {found['connected_calls']} "
            f"answered, reaching {found['people_answered']} people. The counts below are "
            "people, each once, by their latest answered call."
        )
        if found["outcome_tags"]:
            tags = ", ".join(f"{k} {v}" for k, v in found["outcome_tags"].items())
            lines.append(f"People by what their conversation came to: {tags}.")
        if found["business_outcomes"]:
            mine = ", ".join(f"{o['label']} {o['count']}" for o in found["business_outcomes"])
            lines.append(f"People by the agent's own outcomes: {mine}.")
        for field in found["fields"]:
            values = ", ".join(f"{v['value']} {v['count']}" for v in field["values"] if v["count"])
            lines.append(
                f"{field['label']} (people): {values or 'none yet'}; "
                f"not given {field['not_captured']}."
            )
        lines.append(
            f"Leads from this campaign: {found['leads']} ({found['hot_leads']} hot); "
            f"opt-outs {found['opt_outs']}."
        )
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
    from apps.api.tenancy.members import list_pending_invitations
    from apps.api.tenancy.routes import list_members

    members = await list_members(session, MAX_ROWS, _principal(context))
    lines = [
        _clean(f"- {member.name or 'unnamed'} · {member.role}") + f" [user_id {member.id}]"
        for member in members
    ]
    body = _listing(lines, shown_of="team members", nothing="This account has no team members.")
    invitations = await list_pending_invitations(session, limit=MAX_ROWS)
    if invitations:
        body += "\nInvitations not yet accepted:\n" + "\n".join(
            _clean(
                f"- {invitation.email} · {invitation.role} · expires "
                f"{_date(invitation.expires_at)} · sent {invitation.send_count} time(s)"
            )
            + f" [invitation_id {invitation.id}]"
            for invitation in invitations
        )
    return body


# --- voices_offered --------------------------------------------------------------------


async def _voices_offered(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """The voice picker's own route function, `agents.engine_catalogue_routes.
    engine_catalogue` — so the assistant offers exactly the voices the picker offers and
    `agent_edit` accepts."""
    del session, args
    from apps.api.agents.engine_catalogue_routes import engine_catalogue

    catalogue = await engine_catalogue(_principal(context))
    rows = [voice for voice in catalogue.voices if voice.offerable][:MAX_ROWS]
    if not rows:
        return _clean(catalogue.note or "No voice can be chosen on this account right now.")
    lines = [
        _clean(f"- {voice.label} · {voice.rung.capitalize()}") + f" [voice_id {voice.voice_id}]"
        for voice in rows
    ]
    return _listing(lines, shown_of="voices", nothing="No voice can be chosen right now.")


# --- billing_settings ------------------------------------------------------------------


async def _billing_settings(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """Credits & billing's settings reads: the spending limits (`caps.read_caps` and
    `read_spend_counters`), auto-recharge (`read_auto_recharge`), the low-credit line
    (`chosen_low_balance_line`) and this month's AI help (`read_ai_quota`)."""
    del args
    from apps.api.billing.ai_quota import read_ai_quota
    from apps.api.billing.auto_recharge import read_auto_recharge
    from apps.api.billing.caps import read_caps, read_spend_counters
    from apps.api.billing.service import LOW_BALANCE_INR, chosen_low_balance_line

    assert context.tenant_id is not None
    tenant_id = context.tenant_id

    def inr(value: Any) -> str:
        return "none" if value is None else display_inr(value)

    caps = await read_caps(session, tenant_id=tenant_id)
    counters = await read_spend_counters(session, tenant_id=tenant_id)
    auto = await read_auto_recharge(session, tenant_id=tenant_id)
    line = await chosen_low_balance_line(session, tenant_id=tenant_id)
    quota = await read_ai_quota(session, tenant_id=tenant_id)
    lines = [
        f"Spending limit this month: the account's own {inr(caps.client_cap_spend)} and "
        f"{caps.client_cap_min or 'no'} minutes; the plan's {inr(caps.admin_cap_spend)}. "
        f"Used {inr(counters.billed_inr)} and {display_decimal(counters.minutes_used)} minutes"
        + ("; outgoing calls are stopped by the limit." if counters.capped else "."),
        (
            f"Auto-recharge on: adds {inr(auto.amount_inr)} below {inr(auto.threshold_inr)}, "
            f"at most {inr(auto.monthly_cap_inr)} a month."
            if auto.enabled
            else "Auto-recharge off"
            + (
                "; a payment method is approved."
                if auto.mandate_status == "confirmed"
                else "; no automatic payment method is approved (the person does that)."
            )
        ),
        (
            f"Low-credit warning below {inr(LOW_BALANCE_INR)} (Calevate's)."
            if line is None
            else "Low-credit warning off."
            if line == 0
            else f"Low-credit warning below {inr(line)}."
        ),
        f"AI help {quota.month}: used {inr(quota.used_inr)} of {inr(quota.allowance_inr)}; "
        + (
            "more can be added now (`ai_allowance_extra`)."
            if quota.extra_unavailable is None
            else f"more cannot be added ({quota.extra_unavailable})."
        ),
        "The assistant never takes payments or approves payment methods.",
    ]
    return _clean("\n".join(lines))


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


# --- agent_known_facts -----------------------------------------------------------------

#: Facts known by heart quoted to the model; the rest are counted.
MAX_KNOWN_SHOWN: Final = 15


async def _agent_known_facts(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`agents/hot_facts.view` — `GET /v1/agents/{id}/known-facts`'s reader (D-896)."""
    from apps.api.agents import hot_facts
    from apps.api.engine import get_engine

    agent_id = _uuid_arg(args, "agent_id")
    if agent_id is None:
        return _missing_id("agent_id", "an `agents_list` lookup")
    if context.tenant_id is None or await roster.agent_by_id(session, agent_id) is None:
        return "No agent with that id in this account."
    found = await hot_facts.view(
        session, tenant_id=context.tenant_id, agent_id=agent_id, engine=get_engine()
    )
    if not found.applies:
        return "This agent carries every fact in its instructions, so it never looks one up."
    if not found.enabled:
        return (
            "Knowing facts by heart is switched off for every agent, so this agent looks "
            "each fact up when a caller asks."
        )
    lines = [
        f"Knows {len(found.by_heart)} fact(s) by heart and looks up "
        f"{found.looked_up_total} other(s) when asked."
    ]
    lines += [
        _clean(f"- by heart: {item.text} (asked on {item.asks} recent call(s))")
        for item in found.by_heart[:MAX_KNOWN_SHOWN]
    ]
    if found.computed_at is None:
        lines.append("Its facts have not been chosen yet; that happens within the day.")
    else:
        lines.append(f"Last chosen {ist_stamp(found.computed_at)} from {found.calls_read} call(s).")
    lines.append("The owner sees the same on the agent's Training tab.")
    return "\n".join(lines)


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
    KNOWLEDGE_SOURCES,
    ReadTool(
        name="numbers_list",
        description=(
            "This account's phone numbers (masked) with their agent and price, whether one "
            "can be bought, existing numbers forwarded here, calls at once and the backup phone."
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
            "never takes payments. Limits and auto-recharge: `billing_settings`."
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
            "Lead sources, how new leads are called, leads held after hours, outbound "
            "connections, Sheets connection and failed deliveries, with their ids."
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
            "The team with roles and user ids (`lead_assign` takes one), and invitations "
            "not yet accepted."
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
    # D-893 (L4): one agent's set-up, a part at a time, for the agent actions.
    AGENT_SETTINGS_READ,
    ReadTool(
        name="billing_settings",
        description=(
            "Spending limits, auto-recharge, the low-credit warning and this month's AI help "
            "allowance. For the balance itself use `billing_overview`."
        ),
        parameters=_object({}),
        permission="billing:read",
        run=_billing_settings,
    ),
    ReadTool(
        name="knowledge_questions",
        description=(
            "Questions the agents need answered, most asked first, with drafts and sources."
        ),
        parameters=_object(
            {
                "agent_id": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Null for every agent.",
                }
            }
        ),
        # `GET /v1/teach/questions`' permission: it quotes callers' redacted words.
        permission="calls:read",
        run=_knowledge_questions,
    ),
    ReadTool(
        name="agent_known_facts",
        description=(
            "Which facts one agent knows by heart (answered at once) and how many it looks "
            "up when asked (about a second slower)."
        ),
        parameters=_object(_id_param("agent_id", "agent")),
        permission="agents:read",
        run=_agent_known_facts,
    ),
)

CONSOLE_READ_TOOL_NAMES: Final[frozenset[str]] = frozenset(t.name for t in CONSOLE_READ_TOOLS)

__all__ = ["CONSOLE_READ_TOOLS", "CONSOLE_READ_TOOL_NAMES"]
