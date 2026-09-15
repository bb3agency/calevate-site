"""Is what this client published what their agent is actually answering out of?

WHY THIS MODULE EXISTS
----------------------
A great deal of machinery decides what an agent knows — a content-addressed pack frozen at
publish (`kb/pack.py`), an English gloss that lands on a half-hourly sweep
(`workers/kb_gloss.py`), a stale-pack rebuild driven off the digest, a dense retrieval arm
built at publish (`kb/pack_vectors.py`) — and until this module none of it had a surface.
`agents.knowledge_pack_sha256` was written by the publish path, read by the voice worker,
and shown to nobody. So "I published an hour ago, why doesn't my agent know that?" had no
answer on any screen, and `refresh_published_pack`'s deliberate failure posture — the
publish survives, the pointer does not move, an operator is paged — reached the client as
"published" with no hint that the phone had not heard about it.

WHAT IT COMPUTES, AND WHY IT IS NOT A NEW RECORD OF ANYTHING
-------------------------------------------------------------
It stores nothing and no sweep feeds it. The verdict is the SAME difference
`kb/pack.agents_with_stale_packs` takes — the digest this agent's live corpus implies,
against the digest its row points at — through the same `kb/pack.implied_digest`, so the
screen and the gloss sweep cannot disagree about whether an agent is current. A marker
column recording "delivered" would be a second answer to a question the digest answers
totally, which is the drift the quality bar calls a defect even while both agree.

The one thing the digest cannot give is WHEN, because a hash of a corpus carries no clock,
and that is the whole of `agents.knowledge_pack_recorded_at` (migration f4b18c7d2e59).

HARD RULE 6
-----------
Nothing here is caller-derived. Every field is the client's OWN approved knowledge — counts
of their own chunks, the digest of their own text, and two timestamps. No transcript, no
question a caller asked, no call row is read or joined: the `not_found` an agent answered
on a real call is a different subject with a different surface (`apps/api/insights/`, whose
`detection.py` states the doctrine), and this module deliberately does not reach for it.
Nothing is logged from here at all.

WHY THE FOUR STATES ARE THE FOUR
---------------------------------
Each is a different sentence to the client and a different thing to DO, which is the test a
state has to pass to deserve to exist:

* `no_knowledge` — nothing has ever been published and nothing is live. The agent answers
  the phone and says it does not have that, which is a true statement about an empty
  corpus and not a fault. Action: publish something.
* `live` — the pointer equals the implied digest. What they published is on the phone.
  Action: none.
* `preparing` — the pointer differs AND live chunks are still awaiting their English gloss.
  This is the ordinary, expected gap: a reviewer approves and publishes in one sitting, the
  pack is frozen at that moment, and `workers/kb_gloss.py` writes the gloss afterwards on
  its own clock and rebuilds. It heals itself. Action: wait.
* `not_delivered` — the pointer differs and NOTHING is pending, so no sweep is coming. This
  is `refresh_published_pack`'s survived-storage-failure reaching a screen for the first
  time, and it is the state that had no user-facing error path at all. Action: publish
  again (the pack is content-addressed, so a retry that works costs nothing), and if it
  stays, contact support with `pack_id` and the agent.

The order of the checks is load-bearing: `no_knowledge` is tested FIRST because an empty
corpus still has an implied digest (the digest of no entries is a real 64-hex string, never
NULL), so an agent that has never published would otherwise read as `not_delivered` on the
strength of a NULL pointer — telling a client something is broken on the day they signed up.
That is also why an agent that withdrew its last source is NOT `no_knowledge`: withdrawal
publishes an EMPTY pack and points at it (`refresh_published_pack`), so the pointer is set,
and "they withdrew everything" stays distinguishable from "they never wrote anything down"
exactly as the call path needs it to be.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.kb.gloss import GLOSS_PENDING
from apps.api.kb.pack import implied_digest, read_entries

#: What a client is told, and what each word obliges them to do. Closed on purpose: a fifth
#: word would have to name a fifth ACTION, and the screen renders one sentence per state.
DeliveryState = Literal["no_knowledge", "live", "preparing", "not_delivered"]

#: The ceiling on one read of a tenant's roster. Each agent past the first statement costs
#: one indexed `read_entries` and a pure hash — the same per-agent price
#: `MAX_PACK_AGENTS_PER_TENANT` (25) is sized against twice an hour in `workers/kb_gloss.py`
#: — and this runs once when somebody opens a screen. Sized well above any roster this
#: product expects so the list is never silently truncated in front of a client, and
#: bounded at all because the row count is caller-controlled (D-302): an account mints its
#: own agents, so an unbounded loop here is an unbounded response and an unbounded query
#: count on a request path.
MAX_DELIVERY_AGENTS: Final = 100

#: One row per agent on the roster, with the count that decides `preparing`.
#:
#: **THE LIVE-CHUNK COUNT IS NOT IN THIS STATEMENT ON PURPOSE.** It is `len(read_entries)`,
#: the very entries the digest is taken over, rather than a `count(*)` written here. A count
#: in SQL would be a second spelling of `kb/pack._LIVE_CHUNKS_FROM`'s "live", and the
#: failure mode of a second spelling is a screen reading "3 facts live" about a pack holding
#: four — a discrepancy we invented, in front of the client. So this carries only what
#: `read_entries` cannot: identity, the pointer, its clock, and how much of the corpus is
#: still queued for translation.
#:
#: `gloss_state = 'pending'` rather than `gloss IS NULL`: they are not the same question
#: (`kb/gloss.py` — a chunk that was looked at and correctly needs no gloss is `not_needed`
#: and waits for nothing), and counting the second would leave an all-English knowledge base
#: permanently "preparing".
#:
#: Archived agents are excluded: off the working roster, never dialled, and a retired agent
#: whose pack never caught up is not something to ask a client to act on. `deleted_at IS
#: NULL` is the erasure column — a different exclusion from the same row.
#:
#: `tenant_id` is re-stated on top of RLS for `kb/pack._LIVE_CHUNKS_FROM`'s reason: RLS
#: cannot see a caller passing tenant A's id on a session opened for tenant B as a mistake.
_ROSTER_SQL: Final = """
SELECT a.id,
       a.name,
       a.knowledge_pack_sha256,
       a.knowledge_pack_recorded_at,
       (SELECT count(*)
          FROM kb_chunks c
          JOIN kb_sources s ON s.id = c.source_id
          JOIN kb_documents d ON d.id = c.document_id
         WHERE c.tenant_id = a.tenant_id AND c.agent_id = a.id
           AND c.is_active AND s.is_active
           AND d.gloss_state = :pending) AS awaiting_translation
FROM agents a
WHERE a.tenant_id = :tid AND a.status <> 'archived' AND a.deleted_at IS NULL
ORDER BY a.name, a.id
LIMIT :limit
"""


@dataclass(frozen=True, slots=True)
class AgentDelivery:
    """One agent's answer to "is my knowledge on the phone?".

    `pack_id` is the client's own artefact name and is shown to them deliberately: it is
    what an operator needs quoted in a support conversation, and a digest of the client's
    own approved text is not that text — the same reading `kb/pack.publish_pack` takes when
    it logs the id. NULL exactly when nothing has ever been recorded for this agent.

    `live_chunks` is what the corpus implies RIGHT NOW, not what the delivered pack holds —
    those differ by definition in `preparing` and `not_delivered`, and the delivered count
    sits inside an object in a bucket. Fetching it would cost a storage GET per agent on a
    screen read, to report a number the client cannot act on, so it is not claimed.
    """

    agent_id: UUID
    agent_name: str
    state: DeliveryState
    pack_id: str | None
    live_chunks: int
    awaiting_translation: int
    last_reached_at: datetime | None


def _state(*, pointer: str | None, implied: str, live_chunks: int, awaiting: int) -> DeliveryState:
    """The verdict, as a pure function of four facts — see the module docstring's ordering.

    Kept separate from the read so every state can be driven directly by a test, including
    the combinations a database would have to be corrupted to produce.
    """
    if pointer is None and live_chunks == 0:
        return "no_knowledge"
    if pointer == implied:
        return "live"
    return "preparing" if awaiting > 0 else "not_delivered"


async def tenant_delivery(
    session: AsyncSession, *, tenant_id: UUID, limit: int = MAX_DELIVERY_AGENTS
) -> list[AgentDelivery]:
    """Every agent on this tenant's roster, and whether its knowledge reached the phone.

    THE WHOLE ROSTER AND NOT ONE AGENT, because both callers want it. The Knowledge screen
    is account-wide, and the per-agent panel selects its own row out of the same response
    rather than asking a second route the same question about one id — which would be a
    second door onto one fact, and the door that gets forgotten when the states change.

    Run on the CALLER's tenant-scoped session (hard rule 1): this opens nothing of its own,
    so it can never widen the tenancy of the code that called it, and `tenant_id` is
    re-stated inside the statement on top of RLS. A caller cannot ask about an agent that
    is not theirs — there is no id to pass, and the roster is whatever the policy admits.

    READ-ONLY and lock-free. Every row is a HINT about an instant that has already passed —
    a publish committing mid-read moves an agent from `preparing` to `live` — which is
    harmless here in a way it is not for the sweep: the sweep ACTS on its answer and takes
    `try_lock_agent_publishes` to do it, and this only draws a screen that refetches.
    """
    rows = (
        await session.execute(
            text(_ROSTER_SQL), {"tid": tenant_id, "pending": GLOSS_PENDING, "limit": limit}
        )
    ).all()
    out: list[AgentDelivery] = []
    for row in rows:
        agent_id = UUID(str(row[0]))
        entries = await read_entries(session, tenant_id=tenant_id, agent_id=agent_id)
        out.append(
            AgentDelivery(
                agent_id=agent_id,
                agent_name=row[1],
                state=_state(
                    pointer=row[2],
                    implied=implied_digest(tenant_id, agent_id, entries),
                    live_chunks=len(entries),
                    awaiting=row[4],
                ),
                pack_id=row[2],
                live_chunks=len(entries),
                awaiting_translation=row[4],
                last_reached_at=row[3],
            )
        )
    return out


__all__ = ["MAX_DELIVERY_AGENTS", "AgentDelivery", "DeliveryState", "tenant_delivery"]
