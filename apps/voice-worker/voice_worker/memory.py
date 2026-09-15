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

`GET /v1/engine/caller-data/{engine}` already exists for exactly this class of caller, and
its own docstring says so: it was put in `apps/api` rather than in `apps/voice-runtime`
*because* a caller on the call path may not derive keys or read that store. The worker is
a second instance of that shape, not a new one — so this reuses the endpoint unchanged
rather than adding a second door, and inherits its authentication, its fail-open posture
and `recall()`'s live re-check of the switch for free.

**IT PASSES THE ENGINE REF THE ENDPOINT ASKS FOR, EVEN THOUGH IT KNOWS THE IDS.** The
endpoint resolves `engine_agent_ref → (tenant, agent)` through `engine_agent_routes`, which
this worker could skip: `SessionConfig` already carries both ids. Widening the endpoint to
take them would be the second spelling of one request, and `publish_agent` writes that
routing row for every engine including `pipecat`, so the existing contract answers. The ref
is read out of `agents.engine_agent_ref` by `config.py` rather than rebuilt from
`engine/pipecat.engine_agent_ref_for` — the worker must not import the monolith, and a
restated format string is the drift the quality bar refuses.

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

The caller's number is the input to this module and appears in exactly two places: the
query string of one outbound request, and never anywhere else. It is not a `SessionConfig`
field — that structure is logged field-by-field by `config.py` and is the thing whose
digests are attested, and a phone number has no business in either — so it travels as an
argument to `open_session` and dies with this call. Nothing here logs the number, a
remembered fact, or a provider's error body (which would quote the request). Counts,
booleans and exception TYPE names only.

═══ HARD RULE 7 ═══

**NOTHING HERE SPENDS MONEY, AND NOTHING IS METERED, BECAUSE NOTHING IS BOUGHT.** The read
is one HTTP call to our own API, which answers from two indexed Postgres reads and an HMAC.
`docs/PIPECAT-MIGRATION.md` §10.4 prices caller memory at "two embedding calls per call" —
that is the SUPERMEMORY design (§8, box 3), which is not adopted: our store is
`caller_memories`, recalled by recency with no embedding on either side
(`compliance/caller_memory.recall` argues why there is no relevance channel here at all).
The WRITE half does cost a model call and is already metered where it happens —
`workers/caller_memory_distil.py` through `record_ai_assist_usage`. No price is wired here,
attested or otherwise, because there is no unit to price.
"""

from __future__ import annotations

import asyncio
from typing import Any, Final, Protocol

import httpx
from calevate_shared.engine import CALLER_MEMORY_VARIABLE
from loguru import logger

#: How long session assembly may wait on the caller-memory read before the call is
#: assembled without it.
#:
#: ⚠ **AN ASSUMPTION, NOT A MEASUREMENT, AND IT IS STATED AS ONE** —
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
#: **WHY 0.5 AND NOT THE 2.0 s THE PACK GETS.** The server-side ceiling on this answer is
#: already declared: `compliance/caller_data_routes._BUDGET_S` is 0.25 s, after which the
#: endpoint returns `{}` rather than hanging. So the only thing a larger client-side budget
#: could buy is patience with the NETWORK, and 0.5 s is that 0.25 s plus as much again for
#: the round trip and a TLS handshake. Matching the pack's 2.0 s would wait 1.75 s for a
#: reply the other end had already decided not to spend time on. The pack is worth more
#: waiting than this is: without it the agent cannot answer questions about the business at
#: all, whereas without this it merely does not recognise someone.
MEMORY_FETCH_BUDGET_S: Final[float] = 0.5

#: The path `compliance/caller_data_routes.py` mounts, with `{engine}` still to fill.
#: `pipeline.ENGINE_NAME` fills it — the same string `agents.engine`, `engine_agent_routes`
#: and every `CallEvent` this worker emits carry, so there is one spelling of "pipecat" in
#: this container and not two.
CALLER_DATA_PATH: Final[str] = "/v1/engine/caller-data"


class CallerMemoryReader(Protocol):
    """What this agent remembers about one caller. A Protocol for `PackFetcher`'s reason.

    The gate, the substitution and the assembly are pure and testable with no network; the
    lookup is the only part that can be slow, absent or down. Tests hand `open_session` a
    two-line fake and never open a socket.
    """

    async def recall(self, *, engine_agent_ref: str, phone_e164: str) -> tuple[str, ...]: ...


class ApiCallerMemoryReader:
    """`CallerMemoryReader` over `GET /v1/engine/caller-data/{engine}`. Structurally typed.

    It does not inherit the Protocol and does not need to — a class with the right `recall`
    satisfies it (`storage.ObjectStorePackFetcher` and `embedding.GeminiQueryEmbedder` say
    the same of theirs).

    **ONE `httpx.AsyncClient` FOR THE LIFE OF THE PROCESS, NOT ONE PER CALL**, for
    `GeminiQueryEmbedder`'s measured reason: a client per request re-does DNS, TCP and TLS,
    and that handshake was roughly half of a measured round trip from this container. On a
    0.5 s budget that is the difference between an answer and a timeout. Pipecat Cloud
    reuses a container across sessions (§8.2), so the second call on a warm container pays
    none of it. The client is injected so a test owns its transport and this class owns no
    global.

    **THE TOKEN.** One credential, the endpoint's own, carried as a constructor argument
    rather than read from a settings module this container deliberately does not have
    (`config.py`: the worker owns no engine and no bootstrap). ⚠ Its `Settings` field is
    spelled `bolna_caller_data_token` — named for the first engine that called the
    endpoint, before there was a second. Renaming a live console-managed key is a config
    migration and not this change; the name is recorded here so the next reader is not
    hunting for a `pipecat_` spelling that does not exist.
    """

    __slots__ = ("_base_url", "_budget_s", "_client", "_engine", "_token")

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        base_url: str,
        token: str,
        engine: str,
        budget_s: float = MEMORY_FETCH_BUDGET_S,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._engine = engine
        self._budget_s = budget_s

    async def recall(self, *, engine_agent_ref: str, phone_e164: str) -> tuple[str, ...]:
        """What we remember, newest first. `()` for every way this can fail. NEVER RAISES.

        `()` is not an error channel being abused: it is the honest answer to "is there
        anything to tell the model about this person?", and it is the SAME answer a
        first-time caller produces. The prompt already says what an empty block means
        (`CALLER_MEMORY_GUIDANCE`), so there is no degraded state to render and nothing for
        a caller to notice beyond a greeting that does not mention last time.

        An exception instead would abort session assembly — a call that never connects
        because a nicety could not be fetched, which is the trade
        `caller_data_routes.py` refuses one hop away and this must not reintroduce.
        """
        try:
            # TWO TIMERS, AND THEY MEASURE DIFFERENT THINGS — not a belt-and-braces habit.
            # `httpx`'s `timeout=` is PER PHASE: connect, write, read and pool each get the
            # value separately, so a request that spends the budget connecting and the
            # budget again reading has honoured both and taken twice as long as the ring can
            # afford. `MEMORY_FETCH_BUDGET_S` is a WALL CLOCK promise about session assembly,
            # and `asyncio.timeout` is the only thing here that can keep one — which is why
            # `caller_data_routes.py` bounds its own answer the same way. Keeping the httpx
            # value as well is what actually closes the socket rather than merely abandoning
            # the coroutine holding it.
            async with asyncio.timeout(self._budget_s):
                response = await self._client.get(
                    f"{self._base_url}{CALLER_DATA_PATH}/{self._engine}",
                    params={"contact_number": phone_e164, "agent_id": engine_agent_ref},
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=self._budget_s,
                )
                response.raise_for_status()
                body = response.json()
        # Broad and narrowed nowhere, for `GeminiQueryEmbedder.embed`'s reason: a timeout, a
        # refused connection, a 5xx, a 401 on a rotated token and a body that is not JSON
        # all mean one thing to the caller — we have nothing to say about this person — and
        # none of them may reach session assembly as an exception. The TYPE is logged and
        # the message is not: an error body quotes the request, and the request carries the
        # caller's number (hard rule 6).
        except Exception as failure:
            logger.warning("caller memory read failed", reason=type(failure).__name__)
            return ()
        return _facts_of(body)


def _facts_of(body: Any) -> tuple[str, ...]:
    """The remembered facts out of a 2xx body, or `()` for a shape this API does not have.

    **THE WIRE CARRIES ONE RENDERED BLOCK, NOT A LIST**, because the endpoint's answer is
    the engine's variable map: `{CALLER_MEMORY_VARIABLE: render_caller_memory(facts)}`, a
    dash list already bounded by `MAX_CALLER_MEMORY_CHARS`. So this splits it back into
    lines rather than re-deriving anything, and `fill_caller_memory_slot` renders it again
    on the way into the prompt — idempotent, because rendering a dash list of lines that
    are already dash-stripped gives the same block. Parsing our own rendering is worth one
    small ugliness: the alternative is a second response shape on an endpoint whose current
    shape is what the rented engine consumes, and two shapes is how a caller ends up
    hearing something different depending on who dialled.

    Separate from `recall` so the shape handling is exercised with no transport, and
    because "the API answered 200 with something else" is a different failure from "we
    never reached it" even though both answer the caller the same way.
    """
    if not isinstance(body, dict):
        logger.warning("caller memory shape", reason="not_an_object")
        return ()
    rendered = body.get(CALLER_MEMORY_VARIABLE)
    if rendered is None:
        # The ORDINARY answer, and it must not look like a fault: `{}` is what the endpoint
        # returns for a first-time caller, for an agent whose client never switched memory
        # on, and for its own fail-open. Not logged at all — a line per call saying nothing
        # happened is how hard rule 6's real signals get lost.
        return ()
    if not isinstance(rendered, str):
        logger.warning("caller memory shape", reason="not_a_string")
        return ()
    # `removeprefix("- ")` and not `lstrip("- ")`: the second strips EVERY leading hyphen
    # and space, so a fact that legitimately begins with one (`clean_fact` collapses a rule
    # run to a single hyphen rather than deleting it) would come back altered. Exactly the
    # one marker `render_caller_memory` adds is removed, and nothing else.
    return tuple(
        stripped
        for line in rendered.splitlines()
        if (stripped := line.strip().removeprefix("- ").strip())
    )


__all__ = [
    "CALLER_DATA_PATH",
    "MEMORY_FETCH_BUDGET_S",
    "ApiCallerMemoryReader",
    "CallerMemoryReader",
]
