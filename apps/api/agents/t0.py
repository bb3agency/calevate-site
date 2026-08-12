"""The T0 compiler, and the recompile FLOWS §7 has always asked for.

TRD §6: "**T0 Compiled context (0ms):** hot facts compiled into the system prompt at
agent-publish time; **regenerated on KB change**. Answers ~80% with zero retrieval."
FLOWS §7 puts "T0 recompilation" between the version bump and the engine KB sync.

The second half of that sentence was not code. The block was compiled once, by the
wizard's intake step (`admin/intake.py`), and nothing rebuilt it when a client's
knowledge was approved: `kb.publish_source` minted no prompt version and touched no
prompt. So approving new knowledge changed what the agent could RETRIEVE (T3, inside
the engine per D-33) and never what it knows at zero latency — the tier TRD §6 says
answers ~80% of questions. A client watched a source go "live" and their agent kept
quoting the price compiled at onboarding.

**What the block is made of.** PROMPT-GUIDE §2 says [T0 FACTS] is "auto-generated from
intake/KB", so it has two halves and each half has exactly one owner:

    [T0 FACTS]
    Hours: mon 09:30-18:00; sun closed          <- the intake half (admin/intake.py)
    Service: Root canal — ₹8000
    Published knowledge:                        <- T0_KNOWLEDGE_MARKER
    - Fees: A consultation costs 500 rupees.    <- the knowledge half (this module)

The intake half is CARRIED FORWARD from the version the agent points at, never
re-derived. Its input is the answer sheet on `organizations.intake`, which belongs to
the wizard; a second compiler for the same facts is how two screens start disagreeing
about a clinic's opening time. Carrying it forward is also what keeps escalation phone
numbers out of the prompt: they are the one intake answer the compiler deliberately
drops (`admin/intake.py:compile_t0_facts`, asserted by `tests/intake_test.py`), and a
recompile that rebuilt the block from `agents.escalation_config` would be the hole in
that assertion. Nothing in this module reads that column, and the block it produces
contains no byte this system did not already put in a prompt.

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
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.prompts import insert_prompt_version
from apps.api.agents.service import publish_agent
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)

# The section marker PROMPT-GUIDE §2 uses, and the one `admin/intake.py` splices on.
# `tests/t0_recompile_test.py` pins the two spellings together: two modules writing
# different headers would each silently append their own block.
T0_HEADER = "[T0 FACTS]"

# Where the knowledge half starts, INSIDE the block. Deliberately not a `[SECTION]`:
# a line starting with `[` at column 0 ends the T0 block for both splicers, so a
# bracketed marker would leave every knowledge line stranded in the prompt body the
# next time the intake step regenerated the block.
T0_KNOWLEDGE_MARKER = "Published knowledge:"

# ~1,500 characters of knowledge on top of the intake half, inside PROMPT-GUIDE §2's
# ~2,500-token budget for the WHOLE prompt (identity, style, task flow, tools,
# guardrails and wrap all come out of the same allowance, and Telugu costs more tokens
# per character than English). A number, not a guess about tokens: the compiler has
# characters and the budget is a ceiling, so it must be enforced in the unit it holds.
KNOWLEDGE_CHAR_BUDGET = 1500

# Where a freshly compiled block is inserted when the prompt has no block yet — the
# position PROMPT-GUIDE §2's template order puts it in (mirrors `admin/intake.py`).
_INSERT_BEFORE = ("[TASK FLOW]", "[TOOLS]", "[GUARDRAILS]", "[WRAP]")

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


def knowledge_lines(facts: Sequence[KnowledgeFact]) -> tuple[list[str], int]:
    """The knowledge half, capped. Returns (lines, sources skipped for space).

    Whole sources only, in the order given, and the leading `- ` guarantees no line
    can begin with `[` however a client names their source.
    """
    lines: list[str] = []
    used = 0
    skipped = 0
    for fact in facts:
        name, body = _one_line(fact.name), _one_line(fact.text)
        if not body:
            continue
        line = f"- {name}: {body}"
        if used + len(line) > KNOWLEDGE_CHAR_BUDGET:
            skipped += 1
            continue
        used += len(line)
        lines.append(line)
    return lines, skipped


def block_of(body: str | None) -> str | None:
    """The [T0 FACTS] block currently inside a prompt body, if it has one."""
    if not body:
        return None
    lines = body.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith(T0_HEADER)), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
    return "\n".join(lines[start:end]).rstrip()


def intake_half(block: str | None) -> list[str]:
    """The lines of a block that are NOT this module's — everything the intake step
    compiled, header excluded.

    Split on the LAST marker, not the first. Ours is always the final one because the
    knowledge half is appended, so the last occurrence is the true boundary even if a
    client's own booking rules happen to contain the marker's text; splitting on the
    first would let that line silently truncate their facts on every recompile.
    """
    if not block:
        return []
    lines = block.splitlines()
    if lines and lines[0].startswith(T0_HEADER):
        lines = lines[1:]
    boundary = max((i for i, line in enumerate(lines) if line == T0_KNOWLEDGE_MARKER), default=None)
    return lines[:boundary] if boundary is not None else lines


def compile_block(*, previous: str | None, knowledge: Sequence[KnowledgeFact]) -> CompiledT0:
    """`previous` block + today's live knowledge → the block the agent should carry.

    Deterministic: the same previous block and the same knowledge produce a
    byte-identical result, which is what lets `recompile_t0` mint nothing when a
    publish changed no fact (a prompt version per click turns the history into noise
    and re-publishes a live agent for no reason).
    """
    lines = [T0_HEADER, *intake_half(previous)]
    knowledge_half, skipped = knowledge_lines(knowledge)
    if knowledge_half:
        lines.append(T0_KNOWLEDGE_MARKER)
        lines.extend(knowledge_half)
    return CompiledT0(block="\n".join(lines), sources=len(knowledge_half), skipped=skipped)


def splice_t0_block(body: str | None, block: str, *, identity: str) -> str:
    """Put `block` where the prompt's [T0 FACTS] section is, or where it should be.

    Replacing rather than appending is the rule PROMPT-GUIDE §2 states: the block is
    auto-generated and regenerated, so a second copy of stale hours above the fresh
    ones is not a merge, it is an agent that quotes two opening times. Everything
    outside the block — the guardrails an operator wrote by hand, the task flow, the
    wrap — is not this compiler's to touch.

    The twin of `admin/intake.py:splice_t0_block`, and `tests/t0_recompile_test.py`
    pins them to identical output. Not imported from there because `admin` sits above
    both `agents` and `kb` and imports both: reaching upwards would make
    `admin.intake → kb.service → agents.t0 → admin.intake` a cycle. The end state is
    the arrow the other way — intake calling this one — which is a one-line change in
    a module this wave does not own.
    """
    if not body or not body.strip():
        return f"[IDENTITY] {identity}\n{block}\n"

    lines = body.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith(T0_HEADER)), None)
    if start is None:
        anchor = next(
            (
                i
                for i, line in enumerate(lines)
                if any(line.startswith(marker) for marker in _INSERT_BEFORE)
            ),
            len(lines),
        )
        return "\n".join([*lines[:anchor], block, *lines[anchor:]]).rstrip() + "\n"

    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("[")),
        len(lines),
    )
    return "\n".join([*lines[:start], block, *lines[end:]]).rstrip() + "\n"


@dataclass(frozen=True, slots=True)
class _AgentState:
    name: str
    status: str
    engine_agent_ref: str | None
    body: str | None
    compiled: str | None
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
                "(a.system_prompt_id IS DISTINCT FROM a.live_prompt_id) "
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
        script_staged=bool(row[5]),
    )


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
    compiled = compile_block(previous=previous, knowledge=knowledge)

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
    "knowledge_lines",
    "recompile_t0",
    "splice_t0_block",
]
