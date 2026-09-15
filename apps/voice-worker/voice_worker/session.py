"""Starting one call: config, pack, what we remember about the caller, then the pipeline.

**THIS IS THE MIDDLE OF THE SEAM, AND IT IS THE PART THAT WAS MISSING.** `config.py` can
load a `SessionConfig`, `knowledge.py` can load a pack, `pipeline.py` can assemble a call
that searches one — and until this module existed nothing put the three in order, so every
call would have been assembled with `knowledge=None` and every caller told the client had
published nothing. Each of those modules is deliberately ignorant of the other two; this is
where that ignorance is paid for, once.

**THE SECOND AWAITABLE IS CALLER MEMORY, AND IT CLOSES A SEAM THAT WAS NOT MERELY EMPTY.**
`compose_engine_prompt` leaves `CALLER_MEMORY_SLOT` in a memory-enabled agent's prompt for
an ENGINE to substitute per call. On `owned_runtime` there is no engine, so a call assembled
straight from `config.system_prompt` recalled nothing AND handed the model the literal
`{caller_memory}` token as part of its instructions. `load_caller_memory` reads the facts
here — on the ring, concurrently with the pack — and `assemble_call` substitutes the slot in
the message the model reads while the ATTESTED digest stays over the unfilled artefact
(`agents/config_versions.py` puts `caller_memory` out of `prompt_sha256` by name).
`voice_worker/memory.py` holds the gate, the budget and the reason the read is an HTTP call
to our own API rather than a query against the database this container is already connected
to.

**THE ORDER IS THE WHOLE CONTRACT: LOAD, THEN ASSEMBLE.** `assemble_call` is synchronous on
purpose (its own docstring argues it: a synchronous assembler can be exercised with no
network, no loop and no object store), so the ONE awaitable on this path has to be awaited
before it, by somebody. That somebody is here, and the wall clock it spends is the ring —
nobody is waiting on it yet.

**WHO CALLS THIS, AND WHAT IS STILL MISSING — WHICH IS NOW ONE THING AND NOT TWO.**
`runtime.WorkerRuntime.run_call` is the production caller: it owns the container's database
engine, builds the `sink.DatabaseEventSink` from the same four ids it passes here, and runs
what comes back. This paragraph used to say the sink *"is the next wave"* and that nothing
called `start_session` at all; the sink now exists, so what remains outside this repository
is exactly one thing — **the carrier transport, which needs a Plivo account in the India
data region (BLOCKER-1, §6 step 6)**. It stays an ARGUMENT for the reason it always was: the
same assembly runs against a fake in tests and against `FastAPIWebsocketTransport` the day
that account exists, and nothing here has to change when it does.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Final
from uuid import UUID

from calevate_shared.engine import awaits_caller_memory
from calevate_shared.events import CallDirection
from loguru import logger
from pipecat.observers.base_observer import BaseObserver
from pipecat.transports.base_transport import BaseTransport
from sqlalchemy.ext.asyncio import AsyncConnection

from voice_worker.config import load_session_config
from voice_worker.knowledge import (
    PackCache,
    PackFetcher,
    QueryEmbedder,
    SessionKnowledge,
    load_session_knowledge,
)
from voice_worker.memory import CallerMemoryReader
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


async def load_caller_memory(
    config: SessionConfig,
    *,
    reader: CallerMemoryReader | None,
    caller_e164: str | None,
) -> tuple[str, ...]:
    """What this agent may say it remembers about the person now ringing. Never raises.

    **THREE THINGS MUST ALL BE TRUE BEFORE A NUMBER LEAVES THIS PROCESS, AND THE ORDER IS
    THE ARGUMENT.**

    1. **The prompt carries the slot** (`awaits_caller_memory`). That token is emitted on
       exactly one condition — `agents.caller_memory_enabled` — which is the same condition
       under which `compose_opening_line` appends `caller_memory_notice_line`, a column that
       is NOT NULL and `ck_agents_caller_memory_notice_nonempty`. So the slot's presence in
       the immutable config version this worker attested is a PROOF that the agent already
       told the caller it keeps notes. An agent that promised nothing asks nothing, and the
       caller's number never reaches the wire. This is the compliance gate, and it is first
       because it is the one that must hold even when the other two are misconfigured.
    2. **A reader was supplied.** `None` — the default, and what every test and every local
       run gets — is a deployment that has not been wired to the API, and a deployment with
       no reader recalls nothing rather than guessing (`embedder`'s shape, for `embedder`'s
       reason: the absence of a dependency is a complete state, not a degraded one).
    3. **We know who is calling.** The carrier leg is step 6 (BLOCKER-1), so today
       `caller_e164` is `None` on every path; an unknown number is a caller we cannot have
       met, which is the same outcome as a first-time caller.

    A missing `engine_agent_ref` joins the same list: it is the handle the endpoint resolves
    to a tenant and an agent, and without it there is no request to make.

    The server checks the switch AGAIN, live (`compliance/caller_memory.recall`), and that
    is not redundant with gate 1. The prompt answers about PUBLISH time; a client who
    switches memory off afterwards keeps running the old config version until the next
    publish, and only the live read sees the switch move.
    """
    if not awaits_caller_memory(config.system_prompt):
        return ()
    if reader is None or caller_e164 is None or config.engine_agent_ref is None:
        return ()
    return await reader.recall(engine_agent_ref=config.engine_agent_ref, phone_e164=caller_e164)


async def open_session(
    *,
    config: SessionConfig,
    credentials: VendorCredentials,
    transport: BaseTransport,
    sink: NormalizedEventSink,
    fetcher: PackFetcher,
    cache: PackCache | None = None,
    embedder: QueryEmbedder | None = None,
    memory_reader: CallerMemoryReader | None = None,
    caller_e164: str | None = None,
    observers: Sequence[BaseObserver] | None = None,
    stop_secs: float = SMART_TURN_STOP_SECS,
) -> AssembledCall:
    """One assembled call, with its knowledge already in memory.

    The await happens BEFORE `assemble_call` and not inside it, which is the timing the
    whole design rests on: the fetch is bounded (`storage.PACK_FETCH_BUDGET_S`) and spent
    while the phone is ringing, so a slow store delays the answer by at most that bound and
    a dead store does not delay it at all past it. Nothing about a turn changes afterwards:
    every lookup for the rest of the call is in-process, and
    `tests/in_call_lookup_latency_test.py` measures it at **p50 0.31 ms / p95 0.34 ms** on a
    400-entry pack against a 100 ms budget (14 Sep 2026, development container, contended —
    that file states the conditions and re-runs on demand). **THIS SAID `0.501 ms p50` AND
    THE NUMBER HAD NO HARNESS**: it came from an ad-hoc run nobody could repeat, which is
    hard rule 11's "a value already in this repo is NOT verification of itself". The order of
    magnitude was right and the figure is now reproducible.

    **`embedder` IS THE ONE THING ON THIS PATH THAT CAN PUT A NETWORK CALL BACK ON A TURN,
    AND IT IS OFF UNLESS SOMEBODY HANDS ONE IN.** The sentence above stays true for every
    turn the lexical index answers, which is the overwhelming majority; the dense arm runs
    only where it answered `not_found` or `ambiguous` — see `knowledge.py`'s module
    docstring for the measurement, and `pipeline.assemble_call` for why the switch is an
    argument rather than config this container reads for itself.
    """
    # CONCURRENTLY, SO THE TWO BUDGETS DO NOT ADD. Both are spent on the ring, but awaiting
    # them in sequence would make the worst case `PACK_FETCH_BUDGET_S` + `MEMORY_FETCH_
    # BUDGET_S` of silence before the agent speaks, which is a number nobody chose. They are
    # independent reads of two different stores and neither needs the other's answer.
    # `gather` with no `return_exceptions` is deliberate: both halves promise never to raise
    # (each argues it in its own docstring), so an exception here is a broken promise and
    # must surface as one rather than be swallowed into a call that starts without knowing
    # why it is degraded.
    knowledge, caller_memory = await asyncio.gather(
        load_knowledge(config, fetcher=fetcher, cache=cache),
        load_caller_memory(config, reader=memory_reader, caller_e164=caller_e164),
    )
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
        # HOW MANY FACTS, NEVER WHICH, AND NEVER THE NUMBER THEY ARE ABOUT (hard rule 6).
        # `remembers` is the state an operator cannot otherwise see: an agent whose client
        # switched memory on and whose calls all recall zero facts is either a feature doing
        # nothing or a token that stopped working, and a count tells them apart.
        remembers=len(caller_memory),
    )
    return assemble_call(
        config=config,
        legs=build_vendor_legs(config, credentials),
        transport=transport,
        sink=sink,
        knowledge=knowledge,
        embedder=embedder,
        caller_memory=caller_memory,
        observers=observers,
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
    embedder: QueryEmbedder | None = None,
    memory_reader: CallerMemoryReader | None = None,
    caller_e164: str | None = None,
    observers: Sequence[BaseObserver] | None = None,
) -> AssembledCall:
    """Ids in, a runnable call out. The whole path, in the order it must happen.

    **`caller_e164` IS AN ARGUMENT AND NOT A COLUMN, AND IT IS NOT ON `SessionConfig`.**
    The number belongs to the CALL, not to the agent's configuration — the carrier hands it
    to the entrypoint (step 6) the same way it hands over the transport. Keeping it off
    `SessionConfig` is deliberate under hard rule 6: that structure is logged field by field
    by `config.py` and is the thing whose digests are attested, and a phone number has no
    business in either. It travels as an argument and dies with the call.

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
        embedder=embedder,
        memory_reader=memory_reader,
        caller_e164=caller_e164,
        observers=observers,
    )


__all__ = [
    "load_caller_memory",
    "load_knowledge",
    "open_session",
    "pack_cache",
    "start_session",
]
