"""What this agent already knows about the person now ringing — read while the phone rings.

**THE HALF OF CALLER MEMORY THAT WAS MISSING ON THIS LEG, AND WHAT IT COST.** The store
(`apps/api/compliance/caller_memory.py`), the keyed subject ref, both erasure arms, the
180-day clock, the spoken notice and the hourly distiller that WRITES a fact all shipped
with D-506/D-507/D-513 — for the rented engine. On that leg the engine substitutes
`CALLER_MEMORY_SLOT` per call from `user_data` or from `compliance/caller_data_routes.py`.
**On `owned_runtime` there is no engine to substitute anything**, and `pipeline.
assemble_call` put `config.system_prompt` in front of the model verbatim. So a memory-
enabled agent running on this worker did two wrong things at once: it recalled nothing, and
it read the literal token `{caller_memory}` as part of its instructions. Neither is an
error, neither has an alarm, and both are in the agent's own voice on a live call. This
module and `session.open_session`'s wiring are that seam closed.

═══ WHY AN HTTP READ AND NOT THE DATABASE THIS CONTAINER IS ALREADY CONNECTED TO ═══

`config.py` reads `agent_config_versions` over a tenant-scoped `AsyncConnection`, so "read
`caller_memories` too" looks like the shorter path. It is refused on one fact:
**`caller_memories.subject_ref` is `hmac-sha256` under a key derived from `PLATFORM_KEK`**
(`apps/api/compliance/caller_ref.py`), so a process that resolves a phone number to a row
must hold that key. `PLATFORM_KEK` is the value every console-managed secret in this
product is encrypted under (`.env.example`: *"THE KEY THAT OPENS THE CREDENTIAL STORE"*),
and this container runs on Pipecat Cloud — a third party's infrastructure, one deployable
out from anything else we run. Installing the platform's master key there to save a network
hop on the RING, where nobody is waiting, is not a trade worth making.

So it asks our API, over the worker API and the worker's own credential:
`POST /v1/worker/agents/{engine_agent_ref}/caller-memory`, answered by `compliance/
caller_memory.recall` — the same reader the engine caller-data endpoint uses, so a caller
hears the same thing about themselves whichever way the call is placed. Not that endpoint
itself: it would put a second credential in this container, and it takes the number in its
query string, which an access log records. The ref is the one `SessionConfig` carries and
the server parses it, as the session read does.

═══ THE COMPLIANCE GATE IS THE PROMPT, AND THAT IS THE DESIGN ═══

`agents.caller_memory_notice_line` is what the agent TELLS a caller about keeping notes. It
is NOT NULL and `ck_agents_caller_memory_notice_nonempty`, and `compose_opening_line`
appends it on exactly one condition — `caller_memory_enabled` — which is the same condition
under which `_caller_memory_section` puts `CALLER_MEMORY_SLOT` in the composed prompt. So
`calevate_shared.engine.awaits_caller_memory(prompt)` is a proof, off the immutable
content-addressed artefact this worker attested, that this call's agent already said the
sentence. No slot, no read: no HTTP request is made, no phone number leaves this process,
and nothing can be recalled for an agent that promised nothing.

**AND IT IS NOT THE ONLY GATE, BECAUSE IT ANSWERS ABOUT THE WRONG INSTANT.** The prompt is
what was true at PUBLISH. A client who switches memory off afterwards is still running the
old config version until the next publish, and the artefact would keep saying yes. The
server's `recall()` re-reads `agents.caller_memory_enabled` (and the SPDI vertical refusal)
on every request, so the switch moves and the answer is empty the same second. Two gates,
two instants, and neither is redundant — the local one decides whether to ASK, the remote
one decides what may be ANSWERED.

═══ HARD RULE 6 ═══

The caller's number is the input to this module and appears in exactly one place: the body
of one request to our own API. It is not a `SessionConfig`
field — that structure is logged field-by-field by `config.py` and is the thing whose
digests are attested, and a phone number has no business in either — so it travels as an
argument to `open_session` and dies with this call. Nothing here logs the number, a
remembered fact, or a provider's error body (which would quote the request). Counts,
booleans and exception TYPE names only.

═══ HARD RULE 7 ═══

**NOTHING HERE SPENDS MONEY, AND NOTHING IS METERED, BECAUSE NOTHING IS BOUGHT.** The read
is one request to our own API, which answers from two indexed Postgres reads and an HMAC.
`docs/PIPECAT-MIGRATION.md` §10.4 prices caller memory at "two embedding calls per call" —
that is the SUPERMEMORY design (§8, box 3), which is not adopted: our store is
`caller_memories`, recalled by recency with no embedding on either side
(`compliance/caller_memory.recall` argues why there is no relevance channel here at all).
The WRITE half does cost a model call and is already metered where it happens —
`workers/caller_memory_distil.py` through `record_ai_assist_usage`. No price is wired here,
attested or otherwise, because there is no unit to price.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Protocol

from loguru import logger

if TYPE_CHECKING:
    from voice_worker.api_client import WorkerApiClient

#: How long session assembly may wait on the caller-memory read before the call is
#: assembled without it.
#:
#: ⚠ **AN ASSUMPTION, NOT A MEASUREMENT** —
#: `storage.PACK_FETCH_BUDGET_S`'s pattern, and the same gap: nobody has timed a request
#: from a Pipecat Cloud `ap-south` container to our API, and that measurement
#: (`docs/evidence/pre-build-blockers-2026-09-13.md` §3.6) is what replaces this comment.
#:
#: **WHY THERE IS A BOUND AT ALL**, which does not depend on the number: without one, an
#: API that accepts the connection and then stops talking holds the session in assembly for
#: as long as the socket lives, and the caller hears ringing that never becomes a
#: conversation. With one, the worst case is a returning caller greeted as a stranger,
#: which is the same outcome as having nothing on file — the fail-open the endpoint itself
#: chose, for the same reason, one hop away.
#:
#: **WHY 0.5 AND NOT THE 2.0 s THE PACK GETS.** The answer is two indexed reads and an
#: HMAC, so the budget is for the network: a round trip and a TLS handshake. The pack is
#: worth more waiting than this is: without it the agent cannot answer questions about the
#: business at all, whereas without this it merely does not recognise someone.
MEMORY_FETCH_BUDGET_S: Final[float] = 0.5


class CallerMemoryReader(Protocol):
    """What this agent remembers about one caller. A Protocol for `PackFetcher`'s reason.

    The gate, the substitution and the assembly are pure and testable with no network; the
    lookup is the only part that can be slow, absent or down. Tests hand `open_session` a
    two-line fake and never open a socket.
    """

    async def recall(self, *, engine_agent_ref: str, phone_e164: str) -> tuple[str, ...]: ...


class ApiCallerMemoryReader:
    """`CallerMemoryReader` over the worker API. Structurally typed, as the other readers
    here are.

    It takes the container's one `WorkerApiClient` rather than a client of its own, so it
    shares that client's connection pool, credential and wall-clock budget: a client per
    request re-does DNS, TCP and TLS, which on a 0.5 s budget is the difference between an
    answer and a timeout.
    """

    __slots__ = ("_api", "_budget_s")

    def __init__(self, api: WorkerApiClient, *, budget_s: float = MEMORY_FETCH_BUDGET_S) -> None:
        self._api = api
        self._budget_s = budget_s

    async def recall(self, *, engine_agent_ref: str, phone_e164: str) -> tuple[str, ...]:
        """What we remember, newest first. `()` for every way this can fail. NEVER RAISES.

        `()` is the honest answer to "is there anything to tell the model about this
        person?" and the same one a first-time caller produces, and the prompt already says
        what an empty block means (`CALLER_MEMORY_GUIDANCE`). An exception would abort
        session assembly: a call that never connects because a nicety could not be fetched.
        """
        try:
            answer = await self._api.caller_memory(
                engine_agent_ref, phone_e164, budget_s=self._budget_s
            )
        # Broad on purpose: a timeout, a refused connection, a 5xx, a 401 on a rotated token
        # and an unreadable body all mean we have nothing to say about this person. The TYPE
        # is logged and the message is not, since an error can quote the request (hard rule 6).
        except Exception as failure:
            logger.warning("caller memory read failed", reason=type(failure).__name__)
            return ()
        return tuple(answer.facts)


__all__ = [
    "MEMORY_FETCH_BUDGET_S",
    "ApiCallerMemoryReader",
    "CallerMemoryReader",
]
