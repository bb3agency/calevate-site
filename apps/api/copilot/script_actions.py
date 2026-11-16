"""Pip's fixes for the tests an agent failed (D-724's "Improve my agent", asked of Pip).

`agent_tests_fix` is the Training tab's "Improve my agent" / "Suggest a fix for this": its
executor is `test_conversations.request_improvement`, the function that section's button
called, and the fixes are reviewed there (`ImprovementReview`).

WHY `confirm`. Writing the fixes spends the account's AI allowance, and the tier rule is
"reversible, reaches no caller, spends no money — all three" (`actions_test.
_REVIEWED_IMMEDIATE`). The card says what it costs before anyone is charged.

An agent has no script of its own (D-997, founder 16 Nov 2026): what a call says is written
on an Inbound line or a campaign, each with its own Pip writer on its own page. So the
conversational script writer that once lived here (`agent_script_suggest`, D-820) is retired
rather than re-pointed: its suggestion was kept on the agent's Script tab, which no longer
exists, so a suggestion it wrote could never be kept (CAMPAIGN-WORKER-PLAN Phase 4).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import test_conversations
from apps.api.billing.ai_quota import require_ai_assist
from apps.api.copilot.actions import (
    PROPOSES_ONLY,
    ActionTool,
    Executed,
    Plan,
    ToolActor,
    WriteRefusedError,
    action_schema,
    agent_name,
    parse_args,
)
from apps.api.copilot.identity import ASSISTANT_NAME
from apps.api.copilot.sanitize import strip_invisible

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
    await require_ai_assist(session, tenant_id=actor.tenant_id)
    titles = [strip_invisible(str(r.get("title") or "")) for r in failures]
    count = "1 failed test" if len(failures) == 1 else f"{len(failures)} failed tests"
    return Plan(
        object_id=str(parsed.agent_id),
        title="Suggest fixes for failed tests",
        summary=(
            f"{ASSISTANT_NAME} suggests changes to {name}'s script and facts for {count}. "
            "They wait in the agent's Training tab, where you keep the ones you want. They "
            "are not tested until you put them live and test again."
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
    name = await agent_name(session, parsed.agent_id)
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
        queued=True,
        detail=(
            f"Working out the fixes now. In about two minutes they are on {name}'s Training "
            "tab, under Practice callers. Nothing changes until you keep one."
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
        "Training tab. What a call says is written on its Inbound line or campaign, "
        "not on the agent." + PROPOSES_ONLY,
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
SCRIPT_ACTIONS: Final[tuple[ActionTool, ...]] = (AGENT_TESTS_FIX,)

__all__ = ["AGENT_TESTS_FIX", "SCRIPT_ACTIONS"]
