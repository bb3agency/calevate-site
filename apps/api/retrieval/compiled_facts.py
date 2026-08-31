"""T0 — the ONE retrieval implementation that exists today (TRD §6, `docs/TRD.md:1015`).

TRD §6: *"**T0 Compiled context (0ms):** hot facts compiled into the system prompt at
agent-publish time; regenerated on KB change. Answers ~80% with zero retrieval."* And
`docs/TRD.md:948`: *"the honest statement of the shipped system is: in-call retrieval is T0
and nothing else"*. Verified in code before this adapter was written: `apps/api/agents/t0.py`
compiles the block and stamps it on a NEW `prompt_versions` row, `apps/api/admin/intake.py`
compiles the intake half, and `tests/kb_tiers_test.py` pins both.

So this adapter retrieves nothing new. It reads the block that is ALREADY the agent's
answer sheet and picks the lines that bear on the question. That is worth building because
the block is not addressable today from anywhere except the prompt itself: the dashboard
copilot, which answers a client's questions about their own account, could not tell them
what their agent says about their own refund policy.

WHY THE COMPILED BLOCK AND NOT `kb_documents` DIRECTLY. Three reasons, in order:

1. **Approval is structural here.** Only `kb.service.publish_source` puts knowledge into
   the block, and it only publishes an APPROVED source. Reading `kb_documents` would mean
   re-deriving "what is approved and live" in a second place — the drift CLAUDE.md calls a
   defect even when both copies are right today.
2. **It is what the agent actually says.** A dashboard answering from a different corpus
   than the caller hears is worse than not answering.
3. **The escalation numbers are already out of it.** `admin/intake.py::compile_t0_facts`
   deliberately drops the escalation phone numbers from the block (asserted by
   `tests/intake_test.py`), so nothing this adapter can return is a phone number that was
   never in a prompt. Hard rule 6 is inherited rather than re-argued.

RANKING IS DETERMINISTIC AND HAS NO MODEL IN IT. Token overlap between the question and
each line, normalised by the question's length. Not because a better ranker is impossible —
because this tier is the CHEAP path (`routing.py`), and paying for an embedding to rank
eight lines of a client's own opening hours would be the exact "everything agentic" reflex
the router exists to refuse. When the bake-off lands, T3 ranks properly and this stays what
it is.

WHAT IS DELIBERATELY NOT HERE: no embeddings, no vector store, no provider client, no
migration. The D-28 bake-off is open and this file must not pre-empt it.
"""

from __future__ import annotations

import re
import time
from typing import Final
from uuid import UUID

from calevate_shared.retrieval import (
    Passage,
    Provenance,
    RetrievalCapabilities,
    RetrievalRequest,
    RetrievalResult,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.t0 import T0_HEADER, T0_KNOWLEDGE_MARKER
from apps.api.retrieval.capabilities import require_tier

#: OUR name for this implementation. A metric label and a log field; never shown to a
#: client (hard rule 2's reasoning applied to the store).
PROVIDER_NAME: Final = "compiled-facts"

#: What T0 can do, declared once. Everything false except the tier it IS.
#:
#: `per_tenant_namespace` is True and it is not a courtesy: this adapter reads under an RLS
#: session AND filters on `tenant_id` in the statement, so one tenant's question cannot
#: address another's rows by any route (`compiled_facts_rls_test.py` proves it both ways).
#: `deletion_proof` is True for the same structural reason — there is no second copy to
#: prove anything about; deleting the knowledge and re-publishing removes it from the block,
#: which is the whole of the store.
T0_CAPABILITIES: Final = RetrievalCapabilities(
    compiled_facts=True,
    semantic_search=False,
    hybrid_search=False,
    reranking=False,
    per_tenant_namespace=True,
    deletion_proof=True,
    # The request model's own ceiling. Equal by intent: a k this adapter would have to
    # clamp is a k the port should have refused, and clamping silently is the no-op the
    # port forbids.
    max_k=20,
)

#: The most live agents one tenant-wide question reads blocks from. Bounded because every
#: list this repo reads is bounded (D-302) and because a question asked across 400 agents
#: is not a retrieval, it is a report. A tenant at the ceiling is an operator conversation,
#: not a silent truncation — the log line below says so.
_MAX_AGENTS = 25

#: Words that match everything and therefore rank nothing. Deliberately tiny and English —
#: a long stop list is a language model in disguise, and this tier is not allowed one. A
#: Telugu question simply carries no stop words and ranks on its content tokens, which is
#: the correct behaviour, not a gap.
_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "a", "an", "and", "are", "at", "be", "by", "can", "do", "does", "for", "from",
        "have", "how", "i", "in", "is", "it", "me", "my", "of", "on", "or", "our", "the",
        "to", "we", "what", "when", "where", "which", "who", "you", "your",
    }
)  # fmt: skip

#: Unicode-aware word split: Telugu, Devanagari and Latin all tokenise, digits included
#: (a question about "8000" should find the price line).
_WORD = re.compile(r"\w+", re.UNICODE)


def tokens(value: str) -> frozenset[str]:
    """Content tokens of `value`, lowercased. Single characters are dropped: they carry no
    signal and Telugu inflection makes them noisy."""
    return (
        frozenset(token for token in (w.casefold() for w in _WORD.findall(value)) if len(token) > 1)
        - _STOPWORDS
    )


def score_line(question_tokens: frozenset[str], line: str) -> float:
    """Share of the question's content words this line carries, in [0, 1].

    Normalised by the QUESTION rather than by the line, on purpose: normalising by the line
    would rank a two-word heading above the sentence that actually answers the question,
    because the heading has a higher hit RATE while carrying less. A tie between two lines
    that both answer is broken by input order (Python's sort is stable), which keeps the
    block's own reading order — the order the client wrote their facts in.
    """
    if not question_tokens:
        return 0.0
    return len(question_tokens & tokens(line)) / len(question_tokens)


def facts_of(block: str) -> list[str]:
    """The block's fact lines: no header, no section marker, no blanks.

    `T0_HEADER` and `T0_KNOWLEDGE_MARKER` are imported from `agents/t0.py` rather than
    re-spelled. Two modules spelling the same marker is how the block came to have two
    headers once (`tests/t0_recompile_test.py` pins the pair for that reason).
    """
    return [
        stripped
        for stripped in (line.strip() for line in block.splitlines())
        if stripped and stripped != T0_HEADER and stripped != T0_KNOWLEDGE_MARKER
    ]


class CompiledFactsRetriever:
    """The T0 adapter. Constructed with the caller's tenant-scoped session.

    Holding the session rather than taking one per call is what makes the port's shape work
    for a provider that has no session at all: a managed-vector adapter is constructed with
    a client instead, and neither leaks into `RetrievalRequest`. It also means the RLS
    context is the CALLER's — this class never opens a session of its own and therefore can
    never widen the tenancy of the code that used it.
    """

    name = PROVIDER_NAME
    capabilities = T0_CAPABILITIES

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _live_blocks(self, request: RetrievalRequest) -> list[tuple[UUID, str, str]]:
        """(agent_id, agent_name, block) for every LIVE agent in scope that has a block.

        `a.tenant_id = :tid` is REDUNDANT WITH RLS AND IS STILL THERE. RLS is the control;
        this predicate is the belt, and it defends a specific mistake rather than a
        hypothetical one — a caller that passes tenant A's id on a session opened for
        tenant B. Without the predicate that call returns B's knowledge and looks like a
        successful answer about A; with it, it returns nothing.

        `status = 'live'` because a draft or paused agent's block is not what any caller
        hears, and answering a client out of an unpublished draft is the same class of
        error as answering out of an unapproved source.
        """
        rows = (
            await self._session.execute(
                text(
                    "SELECT a.id, a.name, pv.compiled_t0_context "
                    "FROM agents a JOIN prompt_versions pv ON pv.id = a.system_prompt_id "
                    "WHERE a.tenant_id = :tid AND a.status = 'live' "
                    "AND pv.compiled_t0_context IS NOT NULL "
                    "AND (:aid IS NULL OR a.id = :aid) "
                    "ORDER BY a.name LIMIT :cap"
                ),
                {
                    "tid": request.tenant_id,
                    "aid": request.agent_id,
                    "cap": _MAX_AGENTS,
                },
            )
        ).all()
        return [(UUID(str(r[0])), str(r[1]), str(r[2])) for r in rows]

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        """Rank the live agents' compiled fact lines against the question.

        A tier this adapter cannot serve refuses BY NAME first (`require_tier`), before a
        row is read — unless the caller opted into degrading, in which case the result says
        which capability was missing and the caller must surface it.
        """
        started = time.perf_counter()
        missing = self.capabilities.serves(request.tier)
        if missing is not None and not request.allow_degrade:
            require_tier(request.tier, provider=self)

        question_tokens = tokens(request.question)
        scored: list[tuple[float, Passage]] = []
        for agent_id, agent_name, block in await self._live_blocks(request):
            provenance = Provenance(
                # What a person would call it. The agent's name is the client's own word
                # for the thing that answers their phone, which is what makes a citation
                # checkable by them.
                label=f"{agent_name} — published facts",
                tier="t0",
                agent_id=agent_id,
                # No `source_id`: the block is an artifact of many sources plus the intake
                # answers, so naming one source would be a citation that does not check out.
            )
            for line in facts_of(block):
                score = score_line(question_tokens, line)
                if score > 0.0:
                    passage = Passage(text=line[:4000], provenance=provenance, score=score)
                    scored.append((score, passage))

        # Stable: `sorted` on the score alone keeps the block's reading order within ties.
        scored.sort(key=lambda item: item[0], reverse=True)
        return RetrievalResult(
            passages=tuple(passage for _, passage in scored[: request.k]),
            requested_tier=request.tier,
            served_tier="t0",
            unmet_capability=missing,
            provider=self.name,
            elapsed_ms=(time.perf_counter() - started) * 1000.0,
        )

    async def knowledge_epoch(self, request: RetrievalRequest) -> str:
        """`<live agent count>:<highest live prompt version>` for this tenant and scope.

        WHY THIS IS THE RIGHT STAMP, and why the cache needs no publish hook. Publishing
        knowledge does not edit the live prompt version — `agents/t0.py::recompile_t0`
        INSERTS a new `prompt_versions` row and moves the agent's pointer at it (FLOWS §7's
        rollback depends on that immutability). So the version behind a live agent strictly
        identifies the block's content, and the moment an owner corrects their hours the
        stamp changes and every cached answer under the old stamp is unreachable.

        The count is in it because a version alone cannot see an agent going live, being
        paused, or being archived — each of which changes what a tenant-wide question
        should return while every surviving agent keeps its version.

        A rollback moves the pointer BACKWARDS to an earlier version, which lowers the max
        and can re-expose entries cached before the rollforward. That is CORRECT: the block
        is byte-identical to the one those entries were computed from, so the cached answer
        is the true answer again. The stamp identifies content, not time.
        """
        row = (
            await self._session.execute(
                text(
                    "SELECT count(*), coalesce(max(pv.version), 0) "
                    "FROM agents a JOIN prompt_versions pv ON pv.id = a.system_prompt_id "
                    "WHERE a.tenant_id = :tid AND a.status = 'live' "
                    "AND (:aid IS NULL OR a.id = :aid)"
                ),
                {"tid": request.tenant_id, "aid": request.agent_id},
            )
        ).first()
        if row is None:  # pragma: no cover - an aggregate always returns one row
            return "0:0"
        return f"{int(row[0])}:{int(row[1])}"


__all__ = [
    "PROVIDER_NAME",
    "T0_CAPABILITIES",
    "CompiledFactsRetriever",
    "facts_of",
    "score_line",
    "tokens",
]
