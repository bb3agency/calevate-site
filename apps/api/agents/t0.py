"""The T0 compiler, and the recompile FLOWS §7 has always asked for.

TRD §6: "**T0 Compiled context (0ms):** hot facts compiled into the system prompt at
agent-publish time; **regenerated on KB change**. Answers ~80% with zero retrieval."
FLOWS §7 puts "T0 recompilation" between the version bump and the engine KB sync.

The second half of that sentence was not code. The block was compiled once, by the
admin wizard's intake step, and nothing rebuilt it when a client's
knowledge was approved: `kb.publish_source` minted no prompt version and touched no
prompt. So approving new knowledge changed what the agent could RETRIEVE (T3, inside
the engine per D-33) and never what it knows at zero latency — the tier TRD §6 says
answers ~80% of questions. A client watched a source go "live" and their agent kept
quoting the price compiled at onboarding.

**What the block is made of.** PROMPT-GUIDE §2 says [T0 FACTS] is "auto-generated from
intake/KB", so it has two halves and each half has exactly one owner:

    [T0 FACTS]
    Hours: mon 09:30-18:00; sun closed          <- the business half (the profile)
    Service: Root canal — ₹8000
    Published knowledge:                        <- T0_KNOWLEDGE_MARKER
    - Fees: A consultation costs 500 rupees.    <- the knowledge half (published sources)

Both halves are compiled fresh on every recompile, from the client's one business
profile (`tenancy/business_profile.fact_lines`, D-695) and its live knowledge. Every
agent of the client therefore carries the same facts. Escalation numbers never reach the
block: `fact_lines` does not read contacts.

**A recompile is a NEW version, never an edit of the live one.** Same doctrine as
`agents/prompts.py` and FLOWS §7's own rollback: `prompt_versions` is immutable
history, the agent's pointer only ever moves forward, and the artifact
(`compiled_t0_context`, reserved by D-39) is stamped at INSERT rather than updated onto
a row a previous publish already described.

**A recompile does not publish an agent.** It re-publishes one that is ALREADY live,
which is a different sentence. `agents.service.publish_agent` writes `status = 'live'`,
so calling it for a draft or a PAUSED agent would promote an agent no operator signed
off on — FLOWS §1 step 7 makes that promotion a human gate (test call + regression
mini-suite), and a client pasting an FAQ is not that gate. The predicate is therefore
the same one `agents/prompts.py` uses: live agents are pushed, everything else keeps
the new version on our side until someone deliberately publishes it.

**What does not fit stays in the engine KB.** PROMPT-GUIDE §2 budgets the whole prompt
at ~2,500 tokens and says that when [T0 FACTS] pushes past it "facts move to RAG —
that's the signal, not an invitation to trim guardrails". So the knowledge half is
capped (`KNOWLEDGE_CHAR_BUDGET`) and a source that does not fit is skipped WHOLE rather
than cut mid-sentence: the same source is attached to the engine's KB by the same
publish, so what T0 drops is still answerable at T3 — one retrieval slower, not lost.
Cutting a source in half would instead leave the agent reading out a truncated price.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.prompts import insert_prompt_version
from apps.api.agents.service import publish_agent
from apps.api.agents.t0_block import (
    T0_HEADER,
    T0_KNOWLEDGE_MARKER,
    block_of,
    intake_lines,
    splice_t0_block,
)
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.tenancy.business_profile import profile_fact_lines

log = get_logger(__name__)

# ~1,500 characters of knowledge on top of the intake half, inside PROMPT-GUIDE §2's
# ~2,500-token budget for the WHOLE prompt (identity, style, task flow, tools,
# guardrails and wrap all come out of the same allowance, and Telugu costs more tokens
# per character than English). A number, not a guess about tokens: the compiler has
# characters and the budget is a ceiling, so it must be enforced in the unit it holds.
KNOWLEDGE_CHAR_BUDGET = 1500

_NOTES = "T0 recompiled from published knowledge (FLOWS §7)"


@dataclass(frozen=True, slots=True)
class KnowledgeFact:
    """One live knowledge source as the compiler needs it: a name and its text.

    Deliberately not a row: the KB module owns what "live" means and hands this over
    (`kb.service.active_knowledge`), so nothing in `agents/` queries `kb_sources` and
    nothing in `kb/` knows the block's format.
    """

    name: str
    text: str


@dataclass(frozen=True, slots=True)
class CompiledT0:
    """The block plus what an operator would want in a log line: how much knowledge
    reached T0 and how much was left to the engine's KB."""

    block: str
    sources: int
    skipped: int


def _one_line(value: str) -> str:
    """Collapse to a single line of single spaces.

    Two reasons, both structural rather than cosmetic. A knowledge line that contained
    a newline could produce a line starting with `[` (client text, client formatting),
    which both splicers read as the end of the T0 block. And a line that happened to
    equal `T0_KNOWLEDGE_MARKER` would move the boundary between the two halves. One
    source is one line, so neither is expressible.
    """
    return re.sub(r"\s+", " ", value).strip()


def knowledge_line_prefix(name: str) -> str:
    """`- <source name>: ` — the head of the line `knowledge_lines` writes for that source.

    ONE SPELLING, for `T0_HEADER`'s reason. `retrieval/compiled_facts.py` has to map a line
    of the compiled block back to the source it came from, in order to find that source's
    English gloss, and it can only do that by recognising this prefix. A second module
    re-deriving `f"- {name}: "` is how the block came to have two headers once
    (`tests/t0_recompile_test.py` pins that pair for the same reason).

    `_one_line` is applied here rather than by the caller so the two uses cannot disagree
    about whitespace: a source named "Opening\n hours" produces one prefix, whichever side
    asks for it.
    """
    return f"- {_one_line(name)}: "


def knowledge_lines(facts: Sequence[KnowledgeFact]) -> tuple[list[str], int]:
    """The knowledge half, capped. Returns (lines, sources skipped for space).

    Whole sources only, in the order given, and the leading `- ` guarantees no line
    can begin with `[` however a client names their source.
    """
    lines: list[str] = []
    used = 0
    skipped = 0
    for fact in facts:
        body = _one_line(fact.text)
        if not body:
            continue
        line = f"{knowledge_line_prefix(fact.name)}{body}"
        if used + len(line) > KNOWLEDGE_CHAR_BUDGET:
            skipped += 1
            continue
        used += len(line)
        lines.append(line)
    return lines, skipped


def intake_half(block: str | None) -> list[str]:
    """The business lines of a block, header excluded. One spelling with
    `t0_block.intake_lines`, which the business-facts document is cut with too.
    """
    return intake_lines(block)


def compile_block(*, facts: Sequence[str], knowledge: Sequence[KnowledgeFact]) -> CompiledT0:
    """The business profile's lines + today's live knowledge → the block an agent carries.

    Deterministic: the same profile and the same knowledge produce a byte-identical
    result, which is what lets `recompile_t0` mint nothing when nothing changed (a prompt
    version per click turns the history into noise and re-publishes a live agent for no
    reason).
    """
    lines = [T0_HEADER, *facts]
    knowledge_half, skipped = knowledge_lines(knowledge)
    if knowledge_half:
        lines.append(T0_KNOWLEDGE_MARKER)
        lines.extend(knowledge_half)
    return CompiledT0(block="\n".join(lines), sources=len(knowledge_half), skipped=skipped)


@dataclass(frozen=True, slots=True)
class _AgentState:
    name: str
    status: str
    engine_agent_ref: str | None
    body: str | None
    compiled: str | None
    #: The authored structure of the draft, or None for a freeform one.
    structured: dict[str, Any] | None
    # SURFACES §2b: is a hand-written script edit staged behind "Apply to live calls"?
    script_staged: bool


async def _agent_state(session: AsyncSession, agent_id: UUID) -> _AgentState:
    """The agent and the version it points at, in one read.

    Under a tenant-scoped session RLS is the isolation, so another tenant's agent is a
    clean 404 rather than a write that lands nowhere.
    """
    row = (
        await session.execute(
            text(
                "SELECT a.name, a.status, a.engine_agent_ref, pv.body, pv.compiled_t0_context, "
                "(a.system_prompt_id IS DISTINCT FROM a.live_prompt_id), pv.structured_script "
                "FROM agents a LEFT JOIN prompt_versions pv ON pv.id = a.system_prompt_id "
                "WHERE a.id = :aid AND a.deleted_at IS NULL"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    return _AgentState(
        name=str(row[0]),
        status=str(row[1]),
        engine_agent_ref=row[2],
        body=row[3],
        compiled=row[4],
        structured=row[6],
        script_staged=bool(row[5]),
    )


def _structure_to_carry(structured: dict[str, Any] | None) -> dict[str, Any] | None:
    if structured is None or structured.get("raw_override") is not None:
        return None
    return structured


async def recompile_t0(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    knowledge: Sequence[KnowledgeFact],
    created_by: UUID | None = None,
) -> int | None:
    """Rebuild [T0 FACTS] from the live knowledge. Returns the new version, or None.

    None means "nothing changed": the compiled block is byte-identical to the one the
    agent's active version already carries, so no version is minted and a live agent is
    not disturbed. Re-publishing the same source — a double-clicked button, a retry,
    FLOWS §7's rollback onto the version already live — is therefore free.

    The previous block is read from the BODY first and from `compiled_t0_context` only
    as a fallback: the body is what the engine was actually sent, and a version written
    by hand through `agents/prompts.py` carries no artifact at all. Taking the artifact
    first would let a hand-edited prompt and its recorded block disagree, with the
    recompile choosing the copy the caller never heard.

    Engine coherence, and its cost, stated plainly. A LIVE agent is re-published in the
    SAME transaction, for the reason `agents/prompts.py` gives: facts that only land in
    our database are a lie on the admin screen, and an engine failure must roll the new
    version back with it. The caller (`kb.publish_source`) has by then already attached
    the new documents to the engine, which is not transactional — so a prompt push that
    fails aborts the whole publish and leaves the engine holding a copy no row of ours
    mentions. That state is not silent: the next publish attempt finds it
    (`kb.service._reconcile_engine_state`) and refuses with `kb_engine_out_of_sync`
    rather than stacking a second copy. The alternative orderings are worse — pushing
    the prompt BEFORE the KB sync means an agent quoting new facts from a source whose
    attach was rolled back, which is exactly the "answer from either version"
    divergence D-41's detach-then-attach exists to prevent.
    """
    agent = await _agent_state(session, agent_id)
    previous = block_of(agent.body) or agent.compiled
    facts = await profile_fact_lines(session, tenant_id=tenant_id)
    compiled = compile_block(facts=facts, knowledge=knowledge)

    if compiled.block == previous and agent.body and compiled.block in agent.body:
        log.info("t0_unchanged", extra={"agent_id": str(agent_id)})
        return None

    # Training is a FAST-lane change (SURFACES §2b:101: "voice, extraction fields and
    # training apply immediately"), so a recompile applies itself — EXCEPT when a
    # hand-written script edit is already staged behind Apply. It has to be an
    # exception rather than a rule, because the two changes share one column: the
    # block is spliced into the DRAFT body, so applying it would publish the staged
    # script along with it — precisely the blast-radius accident §2b:101 exists to
    # prevent. Deferring costs one retrieval hop and no knowledge: the same sources
    # were attached to the engine's KB by the same publish, so what does not reach T0
    # is still answerable at T3 (see WHAT DOES NOT FIT above). `pending_state` reports
    # the deferral so a client is told, rather than left to notice.
    applies_now = not agent.script_staged
    version = await insert_prompt_version(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        # The agent's own name is the identity line for an agent that has never had a
        # prompt (a client whose first act is uploading knowledge, before the wizard's
        # step 4). `admin/service.py` names it "<business> receptionist", which is the
        # same sentence the intake step compiles — so the two paths produce the same
        # first prompt instead of two houses styles.
        body=splice_t0_block(agent.body, compiled.block, identity=f"{agent.name}."),
        notes=_NOTES,
        created_by=created_by,
        compiled_t0_context=compiled.block,
        # The client's script is unchanged by a recompile, so its authored structure is
        # carried forward; dropping it reopened every structured script in the builder as
        # raw text holding the platform's facts block. A raw-mode script is the exception:
        # its text would still hold the OLD block, so it is reloaded from the new body.
        structured_script=_structure_to_carry(agent.structured),
        apply_live=applies_now,
    )

    live = agent.status == "live" and bool(agent.engine_agent_ref) and applies_now
    if live:
        await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    # Ids and counts only: the block is the client's own prices, staff names and FAQ
    # answers (hard rule 6). `chars` is what an operator needs to see the budget being
    # approached; `skipped` is what tells them facts are living at T3 instead of T0.
    log.info(
        "t0_recompiled",
        extra={
            "agent_id": str(agent_id),
            "prompt_version": version,
            "sources": compiled.sources,
            "skipped": compiled.skipped,
            "chars": len(compiled.block),
            "live": live,
            "staged_behind_script": agent.script_staged,
        },
    )
    return version


__all__ = [
    "KNOWLEDGE_CHAR_BUDGET",
    "T0_HEADER",
    "T0_KNOWLEDGE_MARKER",
    "CompiledT0",
    "KnowledgeFact",
    "block_of",
    "compile_block",
    "intake_half",
    "knowledge_line_prefix",
    "knowledge_lines",
    "recompile_t0",
    "splice_t0_block",
]
