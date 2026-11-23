"""Pip's fixes for the tests an agent failed (D-724's "Improve my agent", asked of Pip).

`agent_tests_fix` is the Training tab's "Improve my agent" / "Suggest a fix for this": its
executor is `test_conversations.request_improvement`. Script fixes are written as a Pip draft
on one of the agent's Inbound lines or campaigns and reviewed on that page; facts wait on the
Training tab (`agents/test_fixes`, D-1017). An agent with several lines or campaigns needs
one named (`holder_id`), so Pip asks the owner which.

WHY `confirm`. Writing the fixes spends the account's AI allowance, and the tier rule is
"reversible, reaches no caller, spends no money — all three" (`actions_test.
_REVIEWED_IMMEDIATE`). The card says what it costs before anyone is charged.

An agent has no script of its own (D-997, founder 16 Nov 2026): what a call says is written
on an Inbound line or a campaign, each with its own Pip writer on its own page. So the
conversational script writer that once lived here (`agent_script_suggest`, D-820) is retired
rather than re-pointed: its suggestion was kept on the agent's Script tab, which no longer
exists, so a suggestion it wrote could never be kept (CAMPAIGN-WORKER-PLAN Phase 4).

`script_draft` is that page's Generate, asked from chat: it calls the same
`request_proposal` the campaign and Inbound line routes call, with the owner's words as the
draft's instruction, so the draft waits on that page for review exactly as one the page
asked for. Without it Pip could only read a script and send the owner elsewhere, and once
printed the CURRENT script back as if it were the changes asked for (20 Nov 2026).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import test_conversations, test_fixes
from apps.api.agents.jobs import agent_jobs
from apps.api.agents.mistake_fixes import Holder
from apps.api.billing.ai_quota import require_ai_assist
from apps.api.campaigns import workspace as campaign_workspace
from apps.api.copilot.actions import (
    PROPOSES_ONLY,
    ActionTool,
    Executed,
    Plan,
    ToolActor,
    WriteRefusedError,
    action_schema,
    agent_name,
    may_act,
    parse_args,
)
from apps.api.copilot.identity import ASSISTANT_NAME
from apps.api.copilot.sanitize import strip_invisible
from apps.api.core.rbac import Permission
from apps.api.inbound import lines as inbound_lines
from apps.workers.campaign_script_ask import INSTRUCTION_MAX, TONES, Tone

# --- fixes for the tests an agent failed (D-724's "Improve my agent", asked of Pip) -------


class _TestsFixArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    test_keys: Annotated[list[Annotated[str, Field(max_length=100)]], Field(max_length=30)] | None
    #: The Inbound line or campaign the script fixes are drafted on; null for the agent's
    #: only one.
    holder_id: UUID | None = None
    #: Not in the schema: signed in by the planner beside `holder_id`.
    holder_kind: Literal["inbound_line", "campaign"] | None = None
    #: Not in the schema: the planner resolves the run and signs it into the canonical
    #: arguments, so a re-plan at approval reads the same run rather than a newer one.
    run_id: UUID | None = None


def _where(holder: test_fixes.FixHolder) -> str:
    kind = "the Inbound line" if holder.kind == "inbound_line" else "the campaign"
    return f"{kind} “{strip_invisible(holder.name)}”"


async def _holder(
    session: AsyncSession, agent_id: UUID, holder_id: UUID | None
) -> test_fixes.FixHolder | None:
    """Where the script fixes go: the named line or campaign, or the agent's only one. With
    several and none named, the person is asked which, by name."""
    holders = await test_fixes.fix_holders(session, agent_id)
    if holder_id is not None:
        found = next((h for h in holders if h.id == holder_id), None)
        if found is None:
            raise WriteRefusedError(
                "`holder_id` is not one of this agent's Inbound lines or campaigns with a "
                "script; use an id from SCREEN STATE's fix_holders",
                plain="That Inbound line or campaign does not use this agent.",
            )
        return found
    if len(holders) > 1:
        names = "; ".join(f"{_where(h)} (id {h.id})" for h in holders)
        raise WriteRefusedError(
            "this agent works on several Inbound lines or campaigns, so ask the person which "
            f"one the script fixes go to, then call again with its `holder_id`: {names}",
            plain="Which Inbound line or campaign should the script fixes go to?",
        )
    return holders[0] if holders else None


async def _plan_tests_fix(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    """READ ONLY. The run, the failures to fix, then the allowance."""
    parsed = parse_args(_TestsFixArgs, args)
    name = await agent_name(session, parsed.agent_id)
    run = (
        await test_conversations.get_run(session, parsed.agent_id, parsed.run_id)
        if parsed.run_id is not None
        else await test_conversations.latest_run(session, parsed.agent_id)
    )
    if run is None or run.status != "done":
        raise WriteRefusedError(
            "this agent has no finished test run, so offer to run its tests first",
            plain="This agent has no finished test run yet.",
        )
    failures = test_conversations.failing(run)
    keys = sorted({strip_invisible(k.strip()) for k in parsed.test_keys or [] if k.strip()})
    if keys:
        known = {str(r.get("key")) for r in failures}
        if not set(keys) <= known:
            raise WriteRefusedError(
                "a `test_keys` entry is not a failed test of the latest run; use the keys "
                "listed in SCREEN STATE, or null for every failed test",
                plain="That is not a failed test of the latest run.",
            )
        failures = [r for r in failures if str(r.get("key")) in set(keys)]
    if not failures:
        raise WriteRefusedError(
            "every test in the latest run passed, so there is nothing to fix",
            plain="Every test in the latest run passed. Nothing to fix.",
        )
    # Rules the platform owns, settings and tests marked wrong are never the script's to fix
    # (D-823): the person is told who can fix them instead.
    failures = [r for r in failures if r in test_conversations.needs_improving(run)]
    if not failures:
        raise WriteRefusedError(
            "none of these failed tests is the script's or the facts' to fix: each result in "
            "the Training tab says who can (a setting to change, or our side, which we are "
            "fixing), so tell the person that instead",
            plain="None of these is the script's to fix. The Training tab says who can.",
        )
    if run.improving:
        raise WriteRefusedError(
            "fixes for this run are already being worked out, so tell the person they will "
            "appear in the agent's Training tab",
            plain="Fixes for this run are already being written.",
        )
    holder = await _holder(session, parsed.agent_id, parsed.holder_id)
    await require_ai_assist(session, tenant_id=actor.tenant_id)
    titles = [strip_invisible(str(r.get("title") or "")) for r in failures]
    count = "1 failed test" if len(failures) == 1 else f"{len(failures)} failed tests"
    return Plan(
        object_id=str(parsed.agent_id),
        title="Suggest fixes for failed tests",
        summary=(
            f"{ASSISTANT_NAME} works out fixes for {count} of {name}. "
            + (
                f"Script fixes become a draft on {_where(holder)}, for you to review there. "
                if holder is not None
                else "This agent has no Inbound line or campaign with a script, so only "
                "facts can be suggested. "
            )
            + "Facts wait in the agent's Training tab."
        ),
        current=None,
        proposed="; ".join(t for t in titles if t) or count,
        cost="Uses your account's AI help allowance.",
        reversal=(
            "Nothing reaches a caller until you keep the draft and put it live. Discard the "
            "draft or leave the facts unkept if you do not want them."
        ),
        args={
            "agent_id": str(parsed.agent_id),
            "test_keys": keys or None,
            "run_id": str(run.id),
            "holder_id": str(holder.id) if holder is not None else None,
            "holder_kind": holder.kind if holder is not None else None,
        },
    )


async def _execute_tests_fix(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`test_conversations.request_improvement` — what the Training tab's button called —
    behind the allowance asked again at the door. It queues the job and answers at once
    (D-748)."""
    parsed = parse_args(_TestsFixArgs, args)
    assert parsed.run_id is not None  # the planner signs it in
    name = await agent_name(session, parsed.agent_id)
    await require_ai_assist(session, tenant_id=actor.tenant_id)
    await test_conversations.request_improvement(
        session,
        tenant_id=actor.tenant_id,
        agent_id=parsed.agent_id,
        run_id=parsed.run_id,
        keys=parsed.test_keys,
        holder=(
            Holder(parsed.holder_kind, parsed.holder_id)
            if parsed.holder_id is not None and parsed.holder_kind is not None
            else None
        ),
        requested_by=actor.user_id,
    )
    return Executed(
        applied=True,
        queued=True,
        detail=(
            "Working out the fixes now. In about two minutes script fixes are a draft on the "
            f"Inbound line or campaign, and facts are on {name}'s Training tab. Nothing "
            "changes until you keep them."
        ),
        audit_summary={
            "agent_id": str(parsed.agent_id),
            "run_id": str(parsed.run_id),
            "tests": len(parsed.test_keys) if parsed.test_keys else None,
        },
    )


AGENT_TESTS_FIX: Final = ActionTool(
    name="agent_tests_fix",
    tier="confirm",
    undo=None,
    # The Training tab's own write permission (`script_routes.ScriptWriter`).
    permission="org:manage",
    object_type="agent",
    audit_action="agent.tests_improvement",
    where="in the agent's Training tab, under Agents",
    schema=action_schema(
        "agent_tests_fix",
        "Suggest fixes for the tests an agent failed in its latest run. Script fixes become "
        "a draft on one of its Inbound lines or campaigns; facts wait on its Training tab."
        + PROPOSES_ONLY,
        {
            "agent_id": {"type": "string", "description": "From SCREEN STATE or `agents_list`."},
            "test_keys": {
                "anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}],
                "description": "Failed test keys from SCREEN STATE; null for all.",
            },
            "holder_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "Inbound line or campaign id for script fixes, from SCREEN "
                "STATE; null when the agent has one.",
            },
        },
    ),
    plan=_plan_tests_fix,
    execute=_execute_tests_fix,
)

#: Registration order is wire order: new actions APPEND.
SCRIPT_ACTIONS: Final[tuple[ActionTool, ...]] = (AGENT_TESTS_FIX,)


# --- a new draft of what an Inbound line or campaign says (the page's Generate) ----------

HolderKind = Literal["inbound_line", "campaign"]

#: The permission each page's Generate route declares: `POST /v1/campaigns/{id}/script/
#: proposal` is `leads:dispatch`, `POST /v1/inbound-lines/{id}/proposal` is `org:manage`.
#: The tool declares the campaign's and the planner asks the line's of a line.
_HOLDER_PERMISSION: Final[dict[str, Permission]] = {
    "campaign": "leads:dispatch",
    "inbound_line": "org:manage",
}

_HOLDER_SQL: Final = (
    "SELECT 'campaign' AS kind, id, name, agent_id FROM campaigns "
    "WHERE id = :hid AND archived_at IS NULL "
    "UNION ALL SELECT 'inbound_line', id, name, agent_id FROM inbound_lines "
    "WHERE id = :hid AND archived_at IS NULL"
)


class _DraftArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID | None = None
    holder_id: UUID | None = None
    #: Its length is checked in the planner, so a long request is refused with what to do
    #: rather than parse_args' bare "wrong shape".
    instruction: str | None = None
    tone: Tone | None = None
    #: Not in the schema: signed in by the planner beside `holder_id`.
    holder_kind: HolderKind | None = None


class _DraftHolder(BaseModel):
    kind: HolderKind
    id: UUID
    name: str
    agent_id: UUID


def _holder_words(holder: _DraftHolder) -> str:
    kind = "the Inbound line" if holder.kind == "inbound_line" else "the campaign"
    return f"{kind} “{strip_invisible(holder.name)}”"


def _page_of(holder: _DraftHolder) -> str:
    return "Inbound" if holder.kind == "inbound_line" else "Campaigns"


async def _draft_holder(session: AsyncSession, parsed: _DraftArgs) -> _DraftHolder:
    """The named line or campaign (RLS scopes the read to this account), or the agent's only
    one; with several and none named, the person is asked which, by name."""
    if parsed.holder_id is not None:
        row = (await session.execute(text(_HOLDER_SQL), {"hid": parsed.holder_id})).first()
        if row is None:
            raise WriteRefusedError(
                "`holder_id` is not an Inbound line or campaign of this account; use an id "
                "from SCREEN STATE, `campaigns_list` or `agent_settings` part script",
                plain="That Inbound line or campaign was not found.",
            )
        holder = _DraftHolder(kind=row.kind, id=row.id, name=str(row.name), agent_id=row.agent_id)
        if parsed.agent_id is not None and holder.agent_id != parsed.agent_id:
            raise WriteRefusedError(
                "that Inbound line or campaign is spoken by a different agent; call again "
                "with only its `holder_id`, or with one of this agent's own",
                plain="That Inbound line or campaign does not use this agent.",
            )
        return holder
    if parsed.agent_id is None:
        raise WriteRefusedError(
            "name the Inbound line or campaign (`holder_id`) or the agent (`agent_id`) whose "
            "script the person wants rewritten",
            plain="Which Inbound line or campaign should be rewritten?",
        )
    jobs = (await agent_jobs(session, parsed.agent_id)).jobs
    if not jobs:
        raise WriteRefusedError(
            "this agent has no Inbound line or campaign, and what a call says is written on "
            "one; tell the person to give the agent one on Inbound or Campaigns first",
            plain="This agent has no Inbound line or campaign yet.",
        )
    if len(jobs) > 1:
        names = "; ".join(
            f"{'Inbound line' if j.kind == 'inbound_line' else 'campaign'} "
            f"“{strip_invisible(j.name)}” (id {j.id})"
            for j in jobs
        )
        raise WriteRefusedError(
            "this agent works on several Inbound lines and campaigns, each with its own "
            "script, so ask the person which one to rewrite, then call again with its "
            f"`holder_id`: {names}",
            plain="Which Inbound line or campaign should be rewritten?",
        )
    job = jobs[0]
    return _DraftHolder(kind=job.kind, id=job.id, name=job.name, agent_id=parsed.agent_id)


async def _draft_state(session: AsyncSession, holder: _DraftHolder) -> tuple[str, str | None]:
    """The holder's main task and the status of Pip's draft on it (None: no draft)."""
    if holder.kind == "campaign":
        space = await campaign_workspace.read_workspace(session, holder.id)
        return space.main_task, None if space.proposal is None else space.proposal.status
    line = await inbound_lines.read_line(session, holder.id)
    return line.main_task, None if line.proposal is None else line.proposal.status


def _ask(parsed: _DraftArgs) -> dict[str, str]:
    """The request's `ask`, spelled as the page's route spells it."""
    ask: dict[str, str] = {}
    if parsed.tone:
        ask["tone"] = parsed.tone
    said = " ".join(strip_invisible(parsed.instruction or "").split())
    if said:
        ask["instruction"] = said
    return ask


async def _plan_draft(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    """READ ONLY. Where the draft goes, whether it may be asked for there, then the
    allowance."""
    parsed = parse_args(_DraftArgs, args)
    ask = _ask(parsed)
    if len(ask.get("instruction", "")) > INSTRUCTION_MAX:
        raise WriteRefusedError(
            f"`instruction` holds at most {INSTRUCTION_MAX} characters. Put every change the "
            "person asked for into that many, in their words where you can, and call again; "
            "never drop a change they asked for",
            plain=f"That request is longer than {INSTRUCTION_MAX} characters.",
        )
    holder = await _draft_holder(session, parsed)
    needs = _HOLDER_PERMISSION[holder.kind]
    if not await may_act(session, actor, needs):
        raise WriteRefusedError(
            f"this person's role may not ask for a new script on {_holder_words(holder)}, "
            "so tell them rather than trying it another way",
            plain="Your role cannot change this script.",
        )
    main_task, status = await _draft_state(session, holder)
    if not main_task.strip():
        raise WriteRefusedError(
            f"{_holder_words(holder)} has no main task yet, and the script is written from "
            f"it; tell the person to write the main task on its page under {_page_of(holder)}",
            plain="Write its main task first.",
        )
    if status == "drafting":
        raise WriteRefusedError(
            f"{ASSISTANT_NAME} is already writing a draft on {_holder_words(holder)}; tell the "
            "person it will wait there for review, and that Stop on that page cancels it",
            plain="A draft is already being written there.",
        )
    await require_ai_assist(session, tenant_id=actor.tenant_id)
    where = _holder_words(holder)
    return Plan(
        object_id=str(holder.agent_id),
        title="Write a new script draft",
        summary=(
            f"{ASSISTANT_NAME} writes a new draft of what {where} says"
            + (" as you asked" if "instruction" in ask else "")
            + (f", in a {parsed.tone} tone" if parsed.tone else "")
            + f". It waits on its page under {_page_of(holder)} for you to review."
            + (" It replaces the draft waiting there now." if status == "ready" else "")
        ),
        current=None,
        proposed=ask.get("instruction") or "A fresh draft from its main task and sources",
        cost="Uses your account's AI help allowance.",
        reversal=(
            "Nothing reaches a caller until you keep the draft and put it live. Discard it "
            "on that page if you do not want it."
        ),
        args={
            "agent_id": str(holder.agent_id),
            "holder_id": str(holder.id),
            "holder_kind": holder.kind,
            "instruction": ask.get("instruction"),
            "tone": parsed.tone,
        },
    )


async def _execute_draft(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """The page route's own `request_proposal`, behind the allowance asked again at the door.
    It queues the writer and answers at once; the draft lands on the holder's page."""
    parsed = parse_args(_DraftArgs, args)
    assert parsed.holder_id is not None and parsed.holder_kind is not None  # signed in
    holder = await _draft_holder(session, parsed)
    await require_ai_assist(session, tenant_id=actor.tenant_id)
    ask = _ask(parsed) or None
    if holder.kind == "campaign":
        proposal_id = (
            await campaign_workspace.request_proposal(
                session,
                tenant_id=actor.tenant_id,
                campaign_id=holder.id,
                requested_by=actor.user_id,
                ask=ask,
            )
        ).id
    else:
        proposal_id = (
            await inbound_lines.request_proposal(
                session,
                tenant_id=actor.tenant_id,
                line_id=holder.id,
                requested_by=actor.user_id,
                ask=ask,
            )
        ).id
    # The typed instruction stays out of the audit row, as on the page: it is free text.
    asked: dict[str, Any] = {"tone": parsed.tone} if parsed.tone else {}
    if ask and "instruction" in ask:
        asked["instructed"] = True
    return Executed(
        applied=True,
        queued=True,
        detail=(
            f"Writing the new draft of {_holder_words(holder)} now. When it is ready it waits "
            f"on its page under {_page_of(holder)}, where you review it and keep or discard "
            "it. Nothing changes on calls until you keep it."
        ),
        # Recorded under the page's own action, so the holder's history reads the same
        # whichever way the draft was asked for.
        audit_action=(
            "campaign.script_requested"
            if holder.kind == "campaign"
            else "inbound_line.script_requested"
        ),
        audit_summary={
            "holder_kind": holder.kind,
            "holder_id": str(holder.id),
            "proposal_id": str(proposal_id),
            **asked,
        },
    )


SCRIPT_DRAFT: Final = ActionTool(
    name="script_draft",
    tier="confirm",
    undo=None,
    permission="leads:dispatch",
    object_type="agent",
    audit_action="campaign.script_requested",
    where="on the Inbound line's or campaign's own page, as a draft to review",
    schema=action_schema(
        "script_draft",
        "Rewrite what an Inbound line or campaign says: its own script writer makes a new "
        "draft from the person's request, which waits on that page for them to review and "
        "keep. The only way to change a script; a script you read is the current wording, "
        "never changes." + PROPOSES_ONLY,
        {
            "agent_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "The agent, when the person named it and not the line.",
            },
            "holder_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "Inbound line or campaign id, from SCREEN STATE, "
                "`campaigns_list` or `agent_settings` part script; null when the agent has "
                "one.",
            },
            "instruction": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": f"Every change asked for, at most {INSTRUCTION_MAX} "
                "characters, in their words; null for a fresh draft.",
            },
            "tone": {
                "anyOf": [{"type": "string", "enum": list(TONES)}, {"type": "null"}],
                "description": "Only when asked for.",
            },
        },
    ),
    plan=_plan_draft,
    execute=_execute_draft,
)

#: Appended at the end of the registry (`write_tools.WRITE_TOOLS`), after every earlier tool.
SCRIPT_DRAFT_ACTIONS: Final[tuple[ActionTool, ...]] = (SCRIPT_DRAFT,)

__all__ = ["AGENT_TESTS_FIX", "SCRIPT_ACTIONS", "SCRIPT_DRAFT", "SCRIPT_DRAFT_ACTIONS"]
