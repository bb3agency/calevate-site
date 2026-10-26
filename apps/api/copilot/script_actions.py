"""Pip's script abilities (D-820): prepare a change to an agent's call script, or fixes for
the tests it failed, for review where each lives.

Founder, 18 Oct 2026: Pip is the one AI assistant, and the Script tab's own "AI helper"
panel is retired in its favour. This action is what the panel did — make one change the
person asked for, draft the whole script from the five owner questions, or turn a
hand-written script into steps — through the same writer (`workers/script_assist.
draft_script`), and it ends where the panel ended: a PROPOSAL the owner keeps part by part
into their draft on the Script tab, or discards. It never writes the draft and never puts
anything live.

WHY `confirm`. Writing the proposal spends the account's AI allowance, and the tier rule is
"reversible, reaches no caller, spends no money — all three" (`actions_test.
_REVIEWED_IMMEDIATE`). The card says what it costs before anyone is charged; what it does
NOT do (touch the draft, reach a caller) is what its `reversal` says.

WHY A JOB BEHIND IT. The executor records the request and queues `draft_script_proposal`
(`agents/script_proposals.request_proposal`): two model legs do not belong inside the
confirm request's transaction (D-748's reason for the improve job). The Script tab shows
the proposal when it is ready.

`agent_tests_fix` is the Training tab's "Improve my agent" / "Suggest a fix for this",
asked of Pip the same way: its executor is `test_conversations.request_improvement`, the
function that section's button called, and the fixes are reviewed there
(`ImprovementReview`), as before.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import script_proposals, test_conversations
from apps.api.agents.script_proposals import (
    MAX_ANSWER_CHARS,
    MAX_CHANGE_CHARS,
    MIN_REQUEST_CHARS,
    ProposalMode,
)
from apps.api.billing.ai_quota import require_ai_assist
from apps.api.copilot.actions import (
    PROPOSES_ONLY,
    ActionTool,
    Executed,
    Plan,
    ToolActor,
    WriteRefusedError,
    action_schema,
    parse_args,
)
from apps.api.copilot.identity import ASSISTANT_NAME
from apps.api.copilot.quotes import quoted_in
from apps.api.copilot.sanitize import strip_invisible
from apps.api.db.ownership import assert_visible
from apps.workers.script_assist import OWNER_QUESTIONS

_NULLABLE_TEXT: Final = {"anyOf": [{"type": "string"}, {"type": "null"}]}

_TITLES: Final[dict[ProposalMode, str]] = {
    "change": "Suggest a change to this script",
    "whole": "Draft this agent's whole script",
    "steps": "Turn the hand-written script into steps",
}


#: Free text the model passes on, bounded so a refusal never carries an unbounded value;
#: the canonical arguments cut it to the field's own limit.
_Said = Annotated[str, Field(max_length=2000)]


class _Answers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Defaults because the canonical arguments keep only the questions that were answered.
    what_you_offer: _Said | None = None
    customers: _Said | None = None
    good_outcome: _Said | None = None
    common_questions: _Said | None = None
    never_say: _Said | None = None


class _ScriptSuggestArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    mode: ProposalMode
    change: _Said | None
    answers: _Answers | None


async def _agent_name(session: AsyncSession, agent_id: UUID) -> str:
    await assert_visible(session, "agent", agent_id)
    name = (
        await session.execute(text("SELECT name FROM agents WHERE id = :aid"), {"aid": agent_id})
    ).scalar()
    return strip_invisible(str(name or "This agent"))


NO_ANSWERS_REASON: Final = "no answers were given, so ask the person the five questions first"


def _whole_rests_on_the_owner(args: Mapping[str, Any], said: Sequence[str]) -> str | None:
    """A whole script is drafted only from answers the owner typed (D-820, D-833).

    The tool description asks Pip to put the five questions first; a production eval
    (19 Oct 2026) saw it call `whole` on "Draft the whole script for this agent" anyway.
    Each answer must be words the person wrote in this conversation (`quotes.quoted_in`),
    so answers Pip made up, or none at all, send it back to ask."""
    if args.get("mode") != "whole":
        return None
    answers = args.get("answers")
    given = (
        {
            key: value
            for key, value in answers.items()
            if key in OWNER_QUESTIONS and isinstance(value, str) and value.strip()
        }
        if isinstance(answers, Mapping)
        else {}
    )
    if not given:
        return NO_ANSWERS_REASON
    invented = [key for key, value in given.items() if not quoted_in(value, said)]
    if not invented:
        return None
    return (
        f"the answers to {', '.join(f'`{key}`' for key in invented)} are not the person's own "
        "words, so ask the person the five questions together and copy each answer from "
        "what they wrote"
    )


def _canonical(parsed: _ScriptSuggestArgs) -> dict[str, Any]:
    change = strip_invisible((parsed.change or "").strip())[:MAX_CHANGE_CHARS]
    answers = {
        key: strip_invisible(value.strip())[:MAX_ANSWER_CHARS]
        for key, value in (parsed.answers.model_dump() if parsed.answers else {}).items()
        if key in OWNER_QUESTIONS and isinstance(value, str) and value.strip()
    }
    return {
        "agent_id": str(parsed.agent_id),
        "mode": parsed.mode,
        "change": change if parsed.mode == "change" else None,
        "answers": answers if parsed.mode == "whole" else None,
    }


def _proposed(mode: ProposalMode, args: Mapping[str, Any]) -> str:
    if mode == "change":
        return str(args["change"])
    if mode == "whole":
        return "A whole script written from the answers: " + "; ".join(
            f"{OWNER_QUESTIONS[key]} {value}" for key, value in (args["answers"] or {}).items()
        )
    return "The same script, laid out as steps you can edit one by one"


async def _plan_script_suggest(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    """READ ONLY. The refusals the model can fix come first, then the allowance."""
    parsed = parse_args(_ScriptSuggestArgs, args)
    name = await _agent_name(session, parsed.agent_id)
    canonical = _canonical(parsed)
    base = await script_proposals.working_script(session, parsed.agent_id)
    if parsed.mode == "steps" and not base.is_raw:
        raise WriteRefusedError(
            "this agent's script is already in steps, so use mode `change` for one change "
            "or `whole` to draft it again"
        )
    if parsed.mode != "steps" and base.is_raw:
        raise WriteRefusedError(
            "this agent's script is written by hand, so offer to turn it into steps first "
            "(mode `steps`) and make the change after the person keeps those"
        )
    written = script_proposals.request_text(
        parsed.mode, canonical["change"], canonical["answers"] or {}, base
    )
    if len(written) < MIN_REQUEST_CHARS:
        raise WriteRefusedError(
            {
                "change": "the change was missing or too short, so ask the person what to change",
                "whole": NO_ANSWERS_REASON,
                "steps": "this agent has no hand-written script to turn into steps",
            }[parsed.mode]
        )
    pending = await script_proposals.read_proposal(session, parsed.agent_id)
    if pending is not None and pending.status == "drafting":
        raise WriteRefusedError(
            "the last change asked for is still being written, so tell the person to wait for "
            "it on the Script tab before asking for another"
        )
    # The allowance, asked before the card: a refusal here (used up, paused) reaches the
    # person now, with its own remediation, rather than after they press Confirm.
    await require_ai_assist(session, tenant_id=actor.tenant_id)
    return Plan(
        object_id=str(parsed.agent_id),
        title=_TITLES[parsed.mode],
        summary=(
            f"{ASSISTANT_NAME} writes a suggestion for “{name}”'s call script. It waits on "
            "the agent's Script tab, where you keep the parts you want into your draft."
        ),
        current=(
            "A suggestion is waiting for review; this one replaces it."
            if pending is not None and pending.status == "ready"
            else None
        ),
        proposed=_proposed(parsed.mode, canonical),
        cost="Uses your account's AI help allowance.",
        reversal=(
            "Nothing in the script changes until you keep the suggestion, and nothing goes "
            "live until you put it live. Discard it on the Script tab if you do not want it."
        ),
        args=canonical,
    )


async def _execute_script_suggest(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """Record the request and queue the writer (`script_proposals.request_proposal`).

    The allowance is asked again here, at the door: the planner's answer is advisory."""
    parsed = parse_args(_ScriptSuggestArgs, args)
    name = await _agent_name(session, parsed.agent_id)
    await require_ai_assist(session, tenant_id=actor.tenant_id)
    proposal = await script_proposals.request_proposal(
        session,
        tenant_id=actor.tenant_id,
        agent_id=parsed.agent_id,
        mode=parsed.mode,
        change=parsed.change,
        answers=parsed.answers.model_dump(exclude_none=True) if parsed.answers else {},
        requested_by=actor.user_id,
    )
    return Executed(
        applied=True,
        detail=(
            f"{ASSISTANT_NAME} is writing it now; it takes about half a minute. Review it on "
            f"“{name}”'s Script tab: nothing reaches the script until you keep it."
        ),
        # Ids and closed-set words only: the request is the client's own business copy.
        audit_summary={
            "agent_id": str(parsed.agent_id),
            "mode": parsed.mode,
            "proposal_id": str(proposal.id),
        },
    )


_ANSWER_PROPERTIES: Final = {
    key: {**_NULLABLE_TEXT, "description": question} for key, question in OWNER_QUESTIONS.items()
}

AGENT_SCRIPT_SUGGEST: Final = ActionTool(
    name="agent_script_suggest",
    tier="confirm",
    undo=None,
    # The Script tab's own write permission (`script_routes.ScriptWriter`).
    permission="org:manage",
    object_type="agent",
    audit_action="agent.script_assist",
    where="on the agent's Script tab, under Agents",
    schema=action_schema(
        "agent_script_suggest",
        "Write a suggested change to an agent's call script; the person reviews it on its "
        "Script tab. For rewriting, adding to or drafting the script; `set_fields` only types "
        "a dictated value into a field on screen. `change`: one change in their words. "
        "`whole`: ask the five questions together first, then copy each answer from their "
        "words. `steps`: a hand-written script into steps. Failed tests: `agent_tests_fix`."
        + PROPOSES_ONLY,
        {
            "agent_id": {
                "type": "string",
                "description": "The agent's id, from the SCREEN STATE or `agents_list`.",
            },
            "mode": {"type": "string", "enum": list(script_proposals.PROPOSAL_MODES)},
            "change": {**_NULLABLE_TEXT, "description": "With `change`: what to change."},
            "answers": {
                "anyOf": [
                    {
                        "type": "object",
                        "properties": _ANSWER_PROPERTIES,
                        "required": list(_ANSWER_PROPERTIES),
                        "additionalProperties": False,
                    },
                    {"type": "null"},
                ],
                "description": "With `whole`: the person's answer to each question.",
            },
        },
    ),
    plan=_plan_script_suggest,
    execute=_execute_script_suggest,
    grounded=_whole_rests_on_the_owner,
)

# --- fixes for the tests an agent failed (D-724's "Improve my agent", asked of Pip) -------


class _TestsFixArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    test_keys: Annotated[list[Annotated[str, Field(max_length=100)]], Field(max_length=30)] | None
    #: Not in the schema: the planner resolves the run and signs it into the canonical
    #: arguments, so a re-plan at approval reads the same run rather than a newer one.
    run_id: UUID | None = None


async def _plan_tests_fix(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    """READ ONLY. The run, the failures to fix, then the allowance."""
    parsed = parse_args(_TestsFixArgs, args)
    name = await _agent_name(session, parsed.agent_id)
    run = (
        await test_conversations.get_run(session, parsed.agent_id, parsed.run_id)
        if parsed.run_id is not None
        else await test_conversations.latest_run(session, parsed.agent_id)
    )
    if run is None or run.status != "done":
        raise WriteRefusedError(
            "this agent has no finished test run, so offer to run its tests first"
        )
    failures = test_conversations.failing(run)
    keys = sorted({strip_invisible(k.strip()) for k in parsed.test_keys or [] if k.strip()})
    if keys:
        known = {str(r.get("key")) for r in failures}
        if not set(keys) <= known:
            raise WriteRefusedError(
                "a `test_keys` entry is not a failed test of the latest run; use the keys "
                "listed in SCREEN STATE, or null for every failed test"
            )
        failures = [r for r in failures if str(r.get("key")) in set(keys)]
    if not failures:
        raise WriteRefusedError("every test in the latest run passed, so there is nothing to fix")
    # Rules the platform owns, settings and tests marked wrong are never the script's to fix
    # (D-823): the person is told who can fix them instead.
    failures = [r for r in failures if r in test_conversations.needs_improving(run)]
    if not failures:
        raise WriteRefusedError(
            "none of these failed tests is the script's or the facts' to fix: each result in "
            "the Training tab says who can (a setting to change, or our side, which we are "
            "fixing), so tell the person that instead"
        )
    if run.improving:
        raise WriteRefusedError(
            "fixes for this run are already being worked out, so tell the person they will "
            "appear in the agent's Training tab"
        )
    await require_ai_assist(session, tenant_id=actor.tenant_id)
    titles = [strip_invisible(str(r.get("title") or "")) for r in failures]
    count = "1 failed test" if len(failures) == 1 else f"{len(failures)} failed tests"
    return Plan(
        object_id=str(parsed.agent_id),
        title="Suggest fixes for failed tests",
        summary=(
            f"{ASSISTANT_NAME} works out changes to “{name}”'s script and facts that fix "
            f"{count}. They wait in the agent's Training tab, where you keep the ones you want."
        ),
        current=None,
        proposed="; ".join(t for t in titles if t) or count,
        cost="Uses your account's AI help allowance.",
        reversal=(
            "Nothing changes until you keep a fix, and nothing goes live until you put it "
            "live. Leave the suggestions unkept if you do not want them."
        ),
        args={
            "agent_id": str(parsed.agent_id),
            "test_keys": keys or None,
            "run_id": str(run.id),
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
    name = await _agent_name(session, parsed.agent_id)
    await require_ai_assist(session, tenant_id=actor.tenant_id)
    await test_conversations.request_improvement(
        session,
        tenant_id=actor.tenant_id,
        agent_id=parsed.agent_id,
        run_id=parsed.run_id,
        keys=parsed.test_keys,
    )
    return Executed(
        applied=True,
        detail=(
            f"{ASSISTANT_NAME} is working out the fixes; it takes up to two minutes. Review "
            f"them in “{name}”'s Training tab: nothing changes until you keep one."
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
        "Suggest fixes for the tests an agent failed in its latest run, kept on its "
        "Training tab. A change the person describes: `agent_script_suggest`." + PROPOSES_ONLY,
        {
            "agent_id": {"type": "string", "description": "From SCREEN STATE or `agents_list`."},
            "test_keys": {
                "anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}],
                "description": "Failed test keys from SCREEN STATE; null for all.",
            },
        },
    ),
    plan=_plan_tests_fix,
    execute=_execute_tests_fix,
)

#: Registration order is wire order: new actions APPEND.
SCRIPT_ACTIONS: Final[tuple[ActionTool, ...]] = (AGENT_SCRIPT_SUGGEST, AGENT_TESTS_FIX)

__all__ = ["AGENT_SCRIPT_SUGGEST", "AGENT_TESTS_FIX", "SCRIPT_ACTIONS"]
