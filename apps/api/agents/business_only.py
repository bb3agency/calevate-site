"""'Just the business': the agent with the company training and knowledge and no script.

An agent is staff with no script of its own (founder, 16 Nov 2026; rememory 7f9ef306,
298ad6cb); what a call is about is written on an inbound line or a campaign. The agent page's
Try it therefore tries the agent on "just the business": its voice, languages, call settings,
actions, the company training and the client's knowledge, with no job's script.

The agent's own engine agent cannot be that holder yet: until every agent's script has moved
to its lines and campaigns (CAMPAIGN-WORKER-PLAN Phase 4), callers still hear the script it
holds. So the holder is the agent's TEST COPY in our developer workspace (`agent_test_copies`,
D-859), which nothing but the owner's own tests rings. Every publish of the copy composes it
from `business_row`, and so does every knowledge attach to it (`kb.service._publish_config`),
because an attach re-sends the whole agent.

The row keeps what describes the agent rather than a job: its opening line (with the notice
words woven into it, D-971, so the notice check reads the same meaning), its identity, its
business line and its speaking style. Everything else of the script goes. An agent with no
opening line of its own opens with the language's composed line for a call it places
(`engine.placed_call_line`), because a test call is one it places to the owner. Every platform
layer (hard rule 5's truthful answers, `CONFIDENTIALITY_RULE`, the speech rules, the notices)
is composed around this body by `compose_engine_prompt` exactly as for any agent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from calevate_shared.call_script import (
    SCRIPT_SCHEMA_VERSION,
    CallScript,
    compile_call_script,
    upgrade_to_v2,
)
from calevate_shared.engine import placed_call_line, spoken_ai_notice
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.t0_block import block_of, splice_t0_block, with_knowledge_of

if TYPE_CHECKING:
    from apps.api.agents.service import AgentRow


def _own_script(agent: AgentRow) -> CallScript | None:
    """The agent's structured script, v2, or None when it has none or holds raw text."""
    structured = agent.get("structured_script")
    if not structured:
        return None
    try:
        script = CallScript.model_validate(structured)
    except ValidationError:
        return None
    return None if script.raw_override is not None else upgrade_to_v2(script)


def business_script(agent: AgentRow) -> CallScript:
    """The agent's own parts of its script (opening, identity, business line, style), and
    nothing of a job."""
    from apps.api.agents.service import posture_of

    own = _own_script(agent)
    fields: dict[str, Any] = {"schema_version": SCRIPT_SCHEMA_VERSION}
    if own is not None:
        fields.update(
            identity=own.identity,
            business_line=own.business_line,
            style=own.style,
        )
    if own is not None and own.opening_line.strip():
        # The woven notice words count only beside the line they were written for.
        fields.update(opening_line=own.opening_line, opening_notices=own.opening_notices)
    else:
        fields["opening_line"] = placed_call_line(
            body=None,
            language=str(agent["language_primary"]),
            business=str(agent.get("business_name") or ""),
            ai_notice=spoken_ai_notice(posture_of(agent)),
        )
    return CallScript(**fields)


async def business_row(session: AsyncSession, *, tenant_id: UUID, agent: AgentRow) -> AgentRow:
    """`agent` with the business-only body in place of its script, so `_to_config` builds the
    holder exactly as it builds the agent and the company training is composed in by it.

    The pinned facts and the [T0 FACTS] block come from the agent's applied body, as a line's
    do; an agent that has never had a body (a new one, before any profile or knowledge change
    compiled one) gets the block compiled now from the same reads `recompile_t0` uses."""
    # Deferred: `agents/t0` and `kb/service` import `agents/service`, which imports this.
    from apps.api.agents.t0 import compile_block
    from apps.api.kb.service import active_knowledge
    from apps.api.tenancy.business_profile import profile_fact_lines

    identity = f"{agent['name']}."
    source = agent.get("prompt")
    if block_of(source) is None:
        compiled = compile_block(
            facts=await profile_fact_lines(session, tenant_id=tenant_id),
            knowledge=await active_knowledge(session, tenant_id=tenant_id),
        )
        if compiled.block:
            source = splice_t0_block(source, compiled.block, identity=identity)
    script = business_script(agent)
    body = with_knowledge_of(source, compile_call_script(script), identity=identity)
    row: dict[str, Any] = dict(agent)
    row["prompt"] = body
    row["structured_script"] = script.model_dump(mode="json")
    return cast("AgentRow", row)


__all__ = ["business_row", "business_script"]
