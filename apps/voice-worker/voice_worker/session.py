"""Starting one call: config out of the database, pack out of the store, then the pipeline.

**THIS IS THE MIDDLE OF THE SEAM, AND IT IS THE PART THAT WAS MISSING.** `config.py` can
load a `SessionConfig`, `knowledge.py` can load a pack, `pipeline.py` can assemble a call
that searches one — and until this module existed nothing put the three in order, so every
call would have been assembled with `knowledge=None` and every caller told the client had
published nothing. Each of those modules is deliberately ignorant of the other two; this is
where that ignorance is paid for, once.

**THE ORDER IS THE WHOLE CONTRACT: LOAD, THEN ASSEMBLE.** `assemble_call` is synchronous on
purpose (its own docstring argues it: a synchronous assembler can be exercised with no
network, no loop and no object store), so the ONE awaitable on this path has to be awaited
before it, by somebody. That somebody is here, and the wall clock it spends is the ring —
nobody is waiting on it yet.

**WHAT IS STILL NOT HERE, PLAINLY.** Nothing in this repository calls `start_session` in
production, because the two things that would are blocked on facts outside it: the carrier
transport needs a Plivo account in the India data region (BLOCKER-1, §6 step 6) and the
`NormalizedEventSink` writer is the next wave. Both are ARGUMENTS here for the reason
`transport` is an argument to `assemble_call` — so the seam this module closes is complete
and testable today, and what remains is a bootstrap that has nothing to bootstrap yet.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from calevate_shared.events import CallDirection
from loguru import logger
from pipecat.transports.base_transport import BaseTransport
from sqlalchemy.ext.asyncio import AsyncConnection

from voice_worker.config import load_session_config
from voice_worker.knowledge import (
    PackCache,
    PackFetcher,
    SessionKnowledge,
    load_session_knowledge,
)
from voice_worker.pipeline import (
    SMART_TURN_STOP_SECS,
    AssembledCall,
    NormalizedEventSink,
    SessionConfig,
    VendorCredentials,
    assemble_call,
    build_vendor_legs,
)

#: The process's pack cache. **ONE PER CONTAINER, WHICH IS THE ONLY PLACEMENT THAT MAKES IT
#: WORTH HAVING.**
#:
#: A cache built per call is a cache that never hits: Pipecat Cloud REUSES a container
#: across sessions (`docs/PIPECAT-MIGRATION.md` §8.2 — "a busy agent's second call
#: downloads nothing"), and a per-session `PackCache()` would download the same pack on
#: every call while looking, in a diff, exactly like a cache.
#:
#: **WHY HERE AND NOT IN `knowledge.py`.** That module is a pure library: no globals, no
#: clock, no network, which is what lets its LRU, its eviction and its cross-tenant
#: identity check be tested exactly. A module-level instance there would hand every
#: importer a shared object they did not ask for — including the test suite, where one
#: test's warm pack becomes another's mystery hit. Process-scoped state belongs to the
#: module that owns the process, and that is this one.
#:
#: **IT IS SAFE TO SHARE ACROSS TENANTS BY CONSTRUCTION, NOT BY DISCIPLINE.** The key is
#: the pack's content digest, which hashes the tenant and the agent along with the entries
#: (`KnowledgePack.digest`), so two clients cannot collide on a key however similar their
#: knowledge is — and `PackCache.get` re-checks both ids anyway and EVICTS a disagreeing
#: entry rather than merely declining it. `tests/voice_worker_session_test.py` proves the
#: isolation by asking for one tenant's digest with another tenant's ids, rather than
#: asserting it.
_PACK_CACHE: Final[PackCache] = PackCache()


def pack_cache() -> PackCache:
    """The process's cache. A function rather than the constant, so a caller cannot rebind
    it and a test can see exactly what production would use."""
    return _PACK_CACHE


async def load_knowledge(
    config: SessionConfig,
    *,
    fetcher: PackFetcher,
    cache: PackCache | None = None,
) -> SessionKnowledge | None:
    """This agent's pack, or `None` when it has none. Never raises — see the note below.

    **`None` HERE MEANS "NO PUBLISHED KNOWLEDGE BASE" AND NOTHING ELSE**, which is why this
    function refuses to fetch when the digest is absent rather than fetching a key built
    from an empty string. `build_knowledge_tool` distinguishes that ordinary, permanent
    state (`no_knowledge_base`) from a pack that should have loaded and did not
    (`temporarily_unavailable`) by comparing it against `config.knowledge_pack_sha256`, and
    the two must not be able to arrive here as the same value.

    Every OTHER failure comes back as a `SessionKnowledge` carrying its reason, because
    `load_session_knowledge` never raises — so there is no error path to invent here, and
    inventing one (a try/except that answered `None`) would erase exactly the distinction
    above.
    """
    digest = config.knowledge_pack_sha256
    if digest is None:
        return None
    return await load_session_knowledge(
        tenant_id=config.tenant_id,
        agent_id=config.agent_id,
        content_sha256=digest,
        fetcher=fetcher,
        cache=pack_cache() if cache is None else cache,
    )


async def open_session(
    *,
    config: SessionConfig,
    credentials: VendorCredentials,
    transport: BaseTransport,
    sink: NormalizedEventSink,
    fetcher: PackFetcher,
    cache: PackCache | None = None,
    stop_secs: float = SMART_TURN_STOP_SECS,
) -> AssembledCall:
    """One assembled call, with its knowledge already in memory.

    The await happens BEFORE `assemble_call` and not inside it, which is the timing the
    whole design rests on: the fetch is bounded (`storage.PACK_FETCH_BUDGET_S`) and spent
    while the phone is ringing, so a slow store delays the answer by at most that bound and
    a dead store does not delay it at all past it. Nothing about a turn changes afterwards:
    every lookup for the rest of the call is in-process, and `docs/PIPECAT-MIGRATION.md`
    §8.1 measures it at 0.501 ms p50 against a 100 ms budget.
    """
    knowledge = await load_knowledge(config, fetcher=fetcher, cache=cache)
    logger.info(
        "session knowledge resolved",
        call_id=config.call_id,
        tenant_id=str(config.tenant_id),
        agent_id=str(config.agent_id),
        # Three states, and an operator needs them apart: no pack configured, a pack that
        # is answering, a pack that is not. Ids and words only (hard rule 6).
        configured=config.knowledge_pack_sha256 is not None,
        available=knowledge is not None and knowledge.available,
        unavailable_reason=None if knowledge is None else knowledge.unavailable_reason,
    )
    return assemble_call(
        config=config,
        legs=build_vendor_legs(config, credentials),
        transport=transport,
        sink=sink,
        knowledge=knowledge,
        stop_secs=stop_secs,
    )


async def start_session(
    connection: AsyncConnection,
    *,
    call_id: str,
    tenant_id: UUID,
    agent_id: UUID,
    direction: CallDirection,
    credentials: VendorCredentials,
    transport: BaseTransport,
    sink: NormalizedEventSink,
    fetcher: PackFetcher,
    cache: PackCache | None = None,
) -> AssembledCall:
    """Ids in, a runnable call out. The whole path, in the order it must happen.

    Split from `open_session` rather than folded into it because the database and the
    object store fail differently and are reached differently: a caller that already holds
    a `SessionConfig` (a warm session, a replay, a local run with no database at all) needs
    the second half and not the first, and `AgentNotRunnableError` is a refusal to start a
    call while every knowledge outcome is a call that starts anyway.
    """
    config = await load_session_config(
        connection,
        call_id=call_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        direction=direction,
    )
    return await open_session(
        config=config,
        credentials=credentials,
        transport=transport,
        sink=sink,
        fetcher=fetcher,
        cache=cache,
    )


__all__ = ["load_knowledge", "open_session", "pack_cache", "start_session"]
