"""Known facts: the facts an agent knows by heart, chosen per agent from evidence (D-896).

WHY. On an engine that keeps the business facts out of the prompt (ThinnestAI,
`HostedAgentLimits.facts_in_knowledge`, the 6 Oct 2026 cost decision) every business question
costs a knowledge search, and a search is a second model pass before the caller hears a word:
about a second on our model (`docs/evidence/latency-research-2026-10-27.md` §0 and §3 lever 1;
ThinnestAI: the agent "has to find the answer before it can start speaking, so the caller
hears a short pause", `thinnest-findings/mirror/snapshots/2026-10-19/pages/channels/voice.md:
494-500`). The founder's decision of 27 Oct 2026: facts in the instructions "when they fit",
chosen dynamically per client, never hard-coded.

This is the "hot facts compiled into the system prompt" tier TRD §6 names, and the
industry's standard split for a voice agent: what is asked most is in the context (no
retrieval round trip), the long tail is retrieved on demand.

HOW THE SET IS CHOSEN, per agent, deterministically and without a model:

1. Candidates: the client's business-profile lines and every paragraph of its LIVE
   knowledge (`kb.service.live_chunks`, which carries the taught facts as one paragraph
   each), whole items only; an item longer than `ITEM_MAX_CHARS` stays searchable.
2. Demand, each piece weighted by age (half-life `HALF_LIFE_DAYS`) and by whether the call
   was this agent's (1) or another agent of the client's (`OTHER_AGENT_WEIGHT`):
   * callers' redacted lines from the last `WINDOW_DAYS` (and their English translation,
     which matches English facts across scripts);
   * the questions the agents could not answer (`knowledge_gaps`), weighted up because an
     unanswered question is proven demand;
   * the agent's own script, a small prior so a new agent with no calls yet still carries
     the facts its script talks about.
   Matching is the gap detector's topic vocabulary (`insights.detection.topics_in`) and
   the T0 retriever's content tokens (`retrieval.compiled_facts.tokens`), each token
   discounted by how many candidates carry it, so the business's own name ranks nothing.
3. An item no demand touches is not chosen: it is looked up when asked ("not every fact
   needs to be in system instructions", founder).
4. The rest is filled by demand per character, whole items, into a budget that is the
   smaller of the console's `hot_facts_max_chars` and what the agent's instructions leave
   under the engine's limit after the script and the platform text (less `RESERVE_CHARS`,
   so a small script edit does not evict a fact). A fact already known keeps a
   `STICKINESS` bonus, so two near-equal facts do not swap places on every run.

AT PUBLISH (`with_known_facts`) the stored set is spliced into the script after the quick
facts, cut whole items from the least-asked end to the console ceiling and to the engine's
limit, so a longer script or new pinned facts never make a publish refuse: the known facts
give way. The prompt then says "answer from the facts in your script when they cover it;
search only for what they do not" (`calevate_shared.engine.FACTS_INLINE_GUIDANCE`).

COST. Every character is re-read on every reply. 6,000 characters is about 1,500 tokens
(ESTIMATE, ~4 characters a token as `billing/own_model_prompt.prompt_tokens_of` counts);
at ~5 replies a minute (ESTIMATE) and the attested ₹0.0238 per 1,000 input tokens of
gemini-3.1-flash-lite (operator-attested, rememory 35a5ccdb) that is about ₹0.18 a minute
uncached and ₹0.02 cached (cached rung ₹0.0238 per 10,000), against ~₹0.14-0.19 saved per
search avoided (a second pass over a ~6-8k token prompt). The ceiling bounds it.

Recomputed by `apps/workers/hot_facts.py` when a client's knowledge or profile changes and
nightly; an agent is republished only when its set actually changed.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.call_script import (
    KNOWN_FACTS_LEAD,
    QUICK_FACTS_HEADER,
    splice_known_facts,
)
from calevate_shared.engine import AgentConfig, VoiceEngine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.prompt_size import measure_config
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.engine.hosted_platform import hosted_agent_limits

log = get_logger(__name__)

#: The worker job that chooses every agent's known facts for one client
#: (`apps/workers/hot_facts.recompute_hot_facts`).
RECOMPUTE_JOB: Final = "recompute_hot_facts"

#: How far back callers' lines are read, and how fast their weight halves.
WINDOW_DAYS: Final = 30
HALF_LIFE_DAYS: Final = 14.0
#: Knowledge gaps older than this no longer count.
GAP_WINDOW_DAYS: Final = 90
#: Caller lines read per choice, newest first. A bound, not a sample size: at ~10 caller
#: lines a call it covers a few hundred recent calls.
MAX_CALLER_TURNS: Final = 4000
#: A line from another agent of the same client counts this much (the facts are the
#: client's, D-689, but each agent's callers ask their own things).
OTHER_AGENT_WEIGHT: Final = 0.5
#: An unanswered question counts this many times a caller's line.
GAP_WEIGHT: Final = 2.0
#: The agent's own script, read as one line at this weight.
SCRIPT_PRIOR: Final = 0.5
#: An item longer than this is never inlined; it stays searchable whole.
ITEM_MAX_CHARS: Final = 500
#: Room left free under the engine's limit so a small script edit does not evict a fact.
RESERVE_CHARS: Final = 1000
#: The bonus a fact already known keeps, so near-equal facts do not swap on every run.
STICKINESS: Final = 1.2
#: Density floor, so a five-character item does not outrank a full answer on length alone.
MIN_DENSITY_CHARS: Final = 60
#: The most facts one agent carries, whatever the room: a list a model scans every turn.
MAX_ITEMS: Final = 60

_MASKS = re.compile(r"\[[^\]]*\]")
_PARAGRAPHS = re.compile(r"\n\s*\n")


@dataclass(frozen=True, slots=True)
class Candidate:
    """One fact the agent could know by heart: the client's approved words, whole."""

    key: str
    text: str
    #: `profile` (the business profile) or `knowledge` (a live source).
    origin: Literal["profile", "knowledge"]
    #: An English rendering used as a second matching key, never said.
    gloss: str | None = None
    written_at: datetime | None = None


@dataclass(slots=True)
class _Scored:
    candidate: Candidate
    score: float = 0.0
    calls: set[UUID] = field(default_factory=set)
    gap_calls: int = 0


@dataclass(frozen=True, slots=True)
class Chosen:
    key: str
    text: str
    #: Calls on which callers asked about it, within the window (and gaps' calls).
    asks: int


@dataclass(frozen=True, slots=True)
class Choice:
    items: tuple[Chosen, ...]
    budget_chars: int
    used_chars: int
    candidates: int
    calls_read: int


def key_of(value: str) -> str:
    return hashlib.sha256(_one_line(value).encode()).hexdigest()[:16]


def digest_of(texts: Sequence[str], *, enabled: bool) -> str:
    payload = json.dumps({"enabled": enabled, "items": list(texts)}, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _one_line(value: str) -> str:
    return " ".join(value.split())


def block_chars(texts: Sequence[str]) -> int:
    """What `texts` add to the script as the known-facts section, separator included."""
    if not texts:
        return 0
    return len("\n".join([KNOWN_FACTS_LEAD, *(f"- {t}" for t in texts)])) + 2


# --- candidates -------------------------------------------------------------------------


def candidates_of(
    profile_lines: Sequence[str], chunks: Sequence[Any], *, excluded: Iterable[str] = ()
) -> list[Candidate]:
    """Whole items, de-duplicated, in the client's own order. `chunks` are
    `kb.service.LiveChunk`s; `excluded` are paragraphs that state nothing (the empty facts
    source's sentence)."""
    skip = {_one_line(e).casefold() for e in excluded}
    seen: set[str] = set()
    out: list[Candidate] = []

    def add(value: str, origin: Literal["profile", "knowledge"], **extra: Any) -> None:
        line = _one_line(value)
        if not line or len(line) > ITEM_MAX_CHARS or line.casefold() in skip:
            return
        key = key_of(line)
        if key in seen:
            return
        seen.add(key)
        out.append(Candidate(key=key, text=line, origin=origin, **extra))

    for line in profile_lines:
        add(line, "profile")
    for chunk in chunks:
        paragraphs = [p for p in _PARAGRAPHS.split(chunk.content) if p.strip()]
        # A chunk's gloss renders the whole chunk; it keys its paragraphs only when the
        # chunk is one paragraph, so a gloss never lends one paragraph another's words.
        gloss = chunk.gloss if len(paragraphs) == 1 else None
        for paragraph in paragraphs:
            add(paragraph, "knowledge", gloss=gloss, written_at=chunk.written_at)
    return out


async def gather_candidates(session: AsyncSession, *, tenant_id: UUID) -> list[Candidate]:
    # Imported here: `kb.service` imports `agents.t0`, which imports `agents.service`,
    # which imports this module.
    from apps.api.kb.service import live_chunks
    from apps.api.teach.facts import NO_FACTS_BODY
    from apps.api.tenancy.business_profile import profile_fact_lines

    return candidates_of(
        await profile_fact_lines(session, tenant_id=tenant_id),
        await live_chunks(session, tenant_id=tenant_id),
        excluded=(NO_FACTS_BODY,),
    )


# --- demand -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Evidence:
    """One piece of demand: words, how much they weigh, and the call they came from."""

    words: str
    weight: float
    call_id: UUID | None = None
    #: An unanswered question's calls, counted as asks.
    gap_calls: int = 0


def decay(at: datetime | None, *, now: datetime) -> float:
    if at is None:
        return 1.0
    age_days = max((now - at).total_seconds(), 0.0) / 86400.0
    return float(0.5 ** (age_days / HALF_LIFE_DAYS))


async def gather_demand(
    session: AsyncSession, *, agent_id: UUID, now: datetime, script: str | None
) -> tuple[list[Evidence], int]:
    """The evidence for one agent, and how many calls it came from. Redacted text only
    (hard rule 6): `text_redacted` and its translation `text_en`, which is made from it."""
    evidence: list[Evidence] = []
    rows = (
        await session.execute(
            text(
                "SELECT t.text_redacted, t.text_en, c.id, c.agent_id, "
                "COALESCE(c.started_at, c.created_at) "
                "FROM transcript_turns t JOIN calls c ON c.id = t.call_id "
                "WHERE t.speaker = 'caller' AND COALESCE(c.started_at, c.created_at) >= :since "
                "ORDER BY COALESCE(c.started_at, c.created_at) DESC, t.idx LIMIT :cap"
            ),
            {"since": now - timedelta(days=WINDOW_DAYS), "cap": MAX_CALLER_TURNS},
        )
    ).all()
    calls: set[UUID] = set()
    for redacted, english, call_id, call_agent, at in rows:
        words = " ".join(part for part in (redacted, english) if part)
        if not words.strip():
            continue
        calls.add(call_id)
        own = 1.0 if call_agent == agent_id else OTHER_AGENT_WEIGHT
        evidence.append(Evidence(words=words, weight=own * decay(at, now=now), call_id=call_id))
    gaps = (
        await session.execute(
            text(
                "SELECT topic_key, topic_label, example_question_redacted, occurrence_count, "
                "call_count, last_seen_at, agent_id FROM knowledge_gaps "
                "WHERE last_seen_at >= :since ORDER BY last_seen_at DESC LIMIT 500"
            ),
            {"since": now - timedelta(days=GAP_WINDOW_DAYS)},
        )
    ).all()
    for key, label, question, occurrences, call_count, seen_at, gap_agent in gaps:
        own = 1.0 if gap_agent == agent_id else OTHER_AGENT_WEIGHT
        evidence.append(
            Evidence(
                words=f"{key.replace('_', ' ')} {label} {question or ''}",
                weight=GAP_WEIGHT * int(occurrences or 1) * own * decay(seen_at, now=now),
                gap_calls=int(call_count or 0),
            )
        )
    if script:
        evidence.append(Evidence(words=script, weight=SCRIPT_PRIOR))
    return evidence, len(calls)


# --- ranking ----------------------------------------------------------------------------


def _keys_of(value: str) -> tuple[frozenset[str], frozenset[str]]:
    from apps.api.insights.detection import topics_in
    from apps.api.retrieval.compiled_facts import tokens

    cleaned = _MASKS.sub(" ", value)
    return tokens(cleaned), topics_in(cleaned)


def rank(
    candidates: Sequence[Candidate],
    evidence: Sequence[Evidence],
    *,
    known: Iterable[str] = (),
) -> list[_Scored]:
    """Every candidate with its demand score, most wanted first per character.

    A candidate's score is the sum over evidence of weight x match, where match is 1 for a
    shared topic plus the idf-weighted share of the candidate's content tokens the evidence
    names. Items nothing asked about score 0 and come last.
    """
    keyed: list[tuple[_Scored, frozenset[str], frozenset[str]]] = []
    by_token: dict[str, list[int]] = defaultdict(list)
    by_topic: dict[str, list[int]] = defaultdict(list)
    for i, candidate in enumerate(candidates):
        toks, topics = _keys_of(f"{candidate.text} {candidate.gloss or ''}")
        keyed.append((_Scored(candidate), toks, topics))
        for tok in toks:
            by_token[tok].append(i)
        for topic in topics:
            by_topic[topic].append(i)
    total = max(len(candidates), 1)
    idf = {tok: math.log(1.0 + total / len(hits)) for tok, hits in by_token.items()}
    norm = [math.sqrt(sum(idf[t] for t in toks)) or 1.0 for _s, toks, _p in keyed]

    for piece in evidence:
        toks, topics = _keys_of(piece.words)
        hit: dict[int, float] = defaultdict(float)
        for topic in topics:
            for i in by_topic.get(topic, ()):
                hit[i] += 1.0
        for tok in toks:
            for i in by_token.get(tok, ()):
                hit[i] += idf[tok] / norm[i]
        for i, match in hit.items():
            scored = keyed[i][0]
            scored.score += piece.weight * match
            if piece.call_id is not None:
                scored.calls.add(piece.call_id)
            scored.gap_calls += piece.gap_calls

    held = set(known)
    for scored, _toks, _topics in keyed:
        if scored.candidate.key in held:
            scored.score *= STICKINESS
    out = [scored for scored, _t, _p in keyed]
    out.sort(
        key=lambda s: (
            -s.score / max(len(s.candidate.text), MIN_DENSITY_CHARS),
            -s.score,
            s.candidate.key,
        )
    )
    return out


def choose(ranked: Sequence[_Scored], *, budget_chars: int) -> list[Chosen]:
    """Whole items in rank order while they fit; one that does not is skipped, never cut."""
    picked: list[Chosen] = []
    texts: list[str] = []
    for scored in ranked:
        if scored.score <= 0 or len(picked) >= MAX_ITEMS:
            break
        if block_chars([*texts, scored.candidate.text]) > budget_chars:
            continue
        texts.append(scored.candidate.text)
        picked.append(
            Chosen(
                key=scored.candidate.key,
                text=scored.candidate.text,
                asks=len(scored.calls) + scored.gap_calls,
            )
        )
    return picked


# --- publish time -----------------------------------------------------------------------


def applies(engine: VoiceEngine) -> bool:
    """Known facts are spliced only where the engine keeps the facts out of the prompt and
    the console switch is on; elsewhere the [T0 FACTS] block already carries them."""
    return get_settings().hot_facts_enabled and hosted_agent_limits(engine).facts_in_knowledge


def fit(texts: Sequence[str], *, ceiling: int) -> list[str]:
    """The longest prefix of `texts` (rank order) whose section fits `ceiling`."""
    kept: list[str] = []
    for value in texts:
        if block_chars([*kept, value]) > ceiling:
            break
        kept.append(value)
    return kept


def with_known_facts(cfg: AgentConfig, texts: Sequence[str], engine: VoiceEngine) -> AgentConfig:
    """`cfg` with the agent's known facts in its script and the answer-first rule on.

    The stored set (rank order) is cut to the console ceiling, then by whole items from the
    least-asked end until the composed instructions fit the engine's limit. A no-op where
    known facts do not apply, so every other engine composes byte-identically.
    """
    if not applies(engine):
        return cfg
    body = cfg.system_prompt or ""
    kept = fit(texts, ceiling=get_settings().hot_facts_max_chars)
    candidate = cfg
    while True:
        spliced = splice_known_facts(body, kept)
        inline = bool(kept) or QUICK_FACTS_HEADER in spliced
        candidate = cfg.model_copy(update={"system_prompt": spliced, "facts_inline": inline})
        if not kept or measure_config(candidate, engine).fits:
            return candidate
        kept = kept[:-1]


# --- storage ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Stored:
    items: tuple[Chosen, ...]
    digest: str
    budget_chars: int
    used_chars: int
    candidates: int
    calls_read: int
    computed_at: datetime


async def load(session: AsyncSession, *, agent_id: UUID) -> Stored | None:
    row = (
        await session.execute(
            text(
                "SELECT items, digest, budget_chars, used_chars, candidates, calls_read, "
                "computed_at FROM agent_hot_facts WHERE agent_id = :aid"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        return None
    items = tuple(
        Chosen(key=str(i["key"]), text=str(i["text"]), asks=int(i.get("asks", 0)))
        for i in (row[0] or [])
    )
    return Stored(
        items=items,
        digest=str(row[1]),
        budget_chars=int(row[2]),
        used_chars=int(row[3]),
        candidates=int(row[4]),
        calls_read=int(row[5]),
        computed_at=row[6],
    )


async def load_texts(session: AsyncSession, *, agent_id: UUID) -> tuple[str, ...]:
    """The stored set's texts in rank order, for `agents/service._load_agent`."""
    stored = await load(session, agent_id=agent_id)
    return tuple(item.text for item in stored.items) if stored else ()


async def _save(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, choice: Choice, digest: str
) -> None:
    await session.execute(
        text(
            "INSERT INTO agent_hot_facts (id, tenant_id, agent_id, items, digest, budget_chars, "
            "used_chars, candidates, calls_read, computed_at, created_at, updated_at) VALUES "
            "(:id, :tid, :aid, CAST(:items AS jsonb), :digest, :budget, :used, :cands, :calls, "
            "now(), now(), now()) ON CONFLICT (agent_id) DO UPDATE SET items = EXCLUDED.items, "
            "digest = EXCLUDED.digest, budget_chars = EXCLUDED.budget_chars, "
            "used_chars = EXCLUDED.used_chars, candidates = EXCLUDED.candidates, "
            "calls_read = EXCLUDED.calls_read, computed_at = now(), updated_at = now()"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "aid": agent_id,
            "items": json.dumps(
                [{"key": c.key, "text": c.text, "asks": c.asks} for c in choice.items],
                ensure_ascii=False,
            ),
            "digest": digest,
            "budget": choice.budget_chars,
            "used": choice.used_chars,
            "cands": choice.candidates,
            "calls": choice.calls_read,
        },
    )


# --- one agent's choice -----------------------------------------------------------------


async def request_recompute(session: AsyncSession, *, tenant_id: UUID) -> None:
    """Queue the choice for every agent of the client, in the caller's transaction, so the
    knowledge change and the promise to act on it commit together."""
    from apps.api.reliability.service import enqueue_outbox

    await enqueue_outbox(session, job=RECOMPUTE_JOB, payload={"tenant_id": str(tenant_id)})


async def request_daily(session: AsyncSession, *, tenant_id: UUID, day: str) -> None:
    """The nightly sweep's queueing: at most once per client per IST `day`, so a retried
    tick queues nothing twice."""
    from apps.api.reliability.service import enqueue_outbox_once

    await enqueue_outbox_once(
        session,
        job=RECOMPUTE_JOB,
        payload={"tenant_id": str(tenant_id), "trigger": "daily"},
        dedupe_key=f"hot-facts:{tenant_id}:{day}",
    )


Outcome = Literal["unchanged", "changed", "republished", "not_applicable"]


async def room_for(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, engine: VoiceEngine
) -> int:
    """Characters the known facts may take: the console ceiling, or what the agent's
    instructions leave under the engine's limit without them (less `RESERVE_CHARS`)."""
    from apps.api.agents.handoff import spec_for
    from apps.api.agents.service import _load_agent, _to_config

    ceiling = get_settings().hot_facts_max_chars
    limit = hosted_agent_limits(engine).prompt_chars
    if limit is None:
        return ceiling
    row = await _load_agent(session, tenant_id, agent_id)
    handoff, _duty = await spec_for(session, dict(row))
    cfg = _to_config(tenant_id, {**row, "hot_facts": ()}, engine=engine, handoff=handoff)
    return max(0, min(ceiling, limit - measure_config(cfg, engine).total - RESERVE_CHARS))


async def recompute_agent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    engine: VoiceEngine,
    now: datetime | None = None,
) -> Outcome:
    """Choose one agent's known facts, store them, and republish a published agent whose
    set changed. Idempotent: the same knowledge and calls choose the same set, and an
    unchanged set writes and republishes nothing. The caller holds the tenant's knowledge
    lock (`kb.service.lock_tenant_knowledge`), the order every publish path keeps."""
    from apps.api.agents.models import is_published
    from apps.api.agents.service import publish_agent

    if not hosted_agent_limits(engine).facts_in_knowledge:
        return "not_applicable"
    agent = (
        await session.execute(
            text(
                "SELECT a.status, a.engine_agent_ref, pv.body FROM agents a "
                "LEFT JOIN prompt_versions pv ON pv.id = COALESCE(a.live_prompt_id, "
                "a.system_prompt_id) WHERE a.id = :aid AND a.deleted_at IS NULL "
                "AND a.status <> 'archived'"
            ),
            {"aid": agent_id},
        )
    ).first()
    if agent is None or not agent[2]:
        return "not_applicable"
    stamp = now or datetime.now(UTC)
    stored = await load(session, agent_id=agent_id)
    enabled = get_settings().hot_facts_enabled
    if enabled:
        candidates = await gather_candidates(session, tenant_id=tenant_id)
        evidence, calls_read = await gather_demand(
            session, agent_id=agent_id, now=stamp, script=str(agent[2])
        )
        ranked = rank(candidates, evidence, known=[i.key for i in stored.items] if stored else ())
        budget = await room_for(session, tenant_id=tenant_id, agent_id=agent_id, engine=engine)
        chosen = choose(ranked, budget_chars=budget)
    else:
        candidates, calls_read, budget, chosen = [], 0, 0, []
    choice = Choice(
        items=tuple(chosen),
        budget_chars=budget,
        used_chars=block_chars([c.text for c in chosen]),
        candidates=len(candidates),
        calls_read=calls_read,
    )
    digest = digest_of([c.text for c in chosen], enabled=enabled)
    await _save(session, tenant_id=tenant_id, agent_id=agent_id, choice=choice, digest=digest)
    if stored is not None and stored.digest == digest:
        return "unchanged"
    log.info(
        "hot_facts_chosen",
        extra={
            "agent_id": str(agent_id),
            "items": len(chosen),
            "used_chars": choice.used_chars,
            "budget_chars": budget,
            "candidates": len(candidates),
            "calls_read": calls_read,
        },
    )
    if is_published(str(agent[0]), agent[1]):
        await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id, take_calls=False)
        return "republished"
    return "changed"


# --- what the owner sees ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KnownFactsView:
    enabled: bool
    #: False where the engine keeps every fact in the instructions anyway.
    applies: bool
    by_heart: tuple[Chosen, ...]
    looked_up: tuple[str, ...]
    looked_up_total: int
    used_chars: int
    budget_chars: int
    calls_read: int
    computed_at: datetime | None


#: Looked-up facts listed on the agent's Training tab; the rest are counted.
LOOKED_UP_SHOWN: Final = 20


async def view(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, engine: VoiceEngine
) -> KnownFactsView:
    """What this agent knows by heart and what it looks up, for the Training tab and Pip.
    The by-heart list is the stored choice; the looked-up list is every other live fact."""
    stored = await load(session, agent_id=agent_id)
    candidates = await gather_candidates(session, tenant_id=tenant_id)
    held = {item.key for item in stored.items} if stored else set()
    rest = [c.text for c in candidates if c.key not in held]
    on = applies(engine)
    return KnownFactsView(
        enabled=get_settings().hot_facts_enabled,
        applies=hosted_agent_limits(engine).facts_in_knowledge,
        by_heart=stored.items if stored and on else (),
        looked_up=tuple(rest[:LOOKED_UP_SHOWN]) if on else (),
        looked_up_total=len(rest) if on else 0,
        used_chars=stored.used_chars if stored and on else 0,
        budget_chars=stored.budget_chars if stored and on else 0,
        calls_read=stored.calls_read if stored and on else 0,
        computed_at=stored.computed_at if stored else None,
    )


__all__ = [
    "HALF_LIFE_DAYS",
    "ITEM_MAX_CHARS",
    "LOOKED_UP_SHOWN",
    "MAX_ITEMS",
    "RECOMPUTE_JOB",
    "RESERVE_CHARS",
    "STICKINESS",
    "WINDOW_DAYS",
    "Candidate",
    "Choice",
    "Chosen",
    "Evidence",
    "KnownFactsView",
    "Outcome",
    "Stored",
    "applies",
    "block_chars",
    "candidates_of",
    "choose",
    "decay",
    "digest_of",
    "fit",
    "gather_candidates",
    "gather_demand",
    "key_of",
    "load",
    "load_texts",
    "rank",
    "recompute_agent",
    "request_daily",
    "request_recompute",
    "room_for",
    "view",
    "with_known_facts",
]
