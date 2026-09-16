"""The worker's one door onto `apps/api` (D-621). Everything it used to reach by SQL.

**WHY THERE IS NO DATABASE CLIENT IN THIS CONTAINER ANY MORE.** `docs/DEPLOYMENT.md` §12.5
gate 6: this process runs on Pipecat Cloud and our Postgres is on the VPS host, reachable
only over the Docker bridge — so the DSN it was deployed with named a host it could not
resolve, and the pool it opened could never have opened. Of the four options recorded at
that gate this is the third: the worker stops touching Postgres and speaks HTTP to
`apps/api`, which keeps the database private and is the only option whose fix is entirely
ours.

**IT IS NOT A NEW SHAPE IN THIS TREE.** `memory.ApiCallerMemoryReader` already reads caller
memory over exactly this transport, with exactly this argument, and its sentence
generalises to everything below: *"Installing the platform's master key there to save a
network hop on the RING, where nobody is waiting, is not a trade worth making."* This class
is that reader's shape widened from one GET to the three calls one call needs — one client
for the process, a Bearer header, and a WALL-CLOCK bound that `httpx`'s per-phase timeout
cannot give on its own.

**THE WIRE MODELS ARE `calevate_shared.worker_api` AND NOTHING HERE RESTATES A FIELD.**
Both ends import them, so a rename is a type error in CI rather than a 422 on a live call.

**HARD RULE 6.** Nothing here logs a body, a URL with a ref in it, an error message from
the far end, or a transcript. What it logs is the CALL id, a count, and an exception TYPE
name. A response body quoting our request would quote the conversation.

**HARD RULE 7.** Nothing here prices anything, and it could not: the request models carry
no money field at all. The server holds the rate card.
"""

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import Any, Final, Self, TypeVar

import httpx
from calevate_shared.worker_api import (
    ObservationBatch,
    ObservationsOut,
    SettlementOut,
    SettlementRequest,
    WorkerSessionOut,
)
from loguru import logger
from pydantic import BaseModel

#: One of the wire models. Bound so `_parse` hands back the type its caller asked for
#: rather than `Any` — a client that widened its own answers would defeat the whole point
#: of both ends importing one module.
_Wire = TypeVar("_Wire", bound=BaseModel)

#: How long session assembly may wait on the configuration read before the call is refused.
#:
#: ⚠ **AN ASSUMPTION, NOT A MEASUREMENT, AND IT IS STATED AS ONE** — `memory.
#: MEMORY_FETCH_BUDGET_S` and `storage.PACK_FETCH_BUDGET_S` carry the same gap and the same
#: note: nobody has timed a request from a Pipecat Cloud `ap-south` container to our API,
#: and that measurement (`docs/evidence/pre-build-blockers-2026-09-13.md` §3.6) is what
#: replaces this comment.
#:
#: **WHY IT IS THE LONGEST OF THE THREE BUDGETS**, which does not depend on the number:
#: without this read there is no call at all. The caller-memory read fails open (a returning
#: caller greeted as a stranger) and the pack fetch degrades (an agent that cannot answer
#: questions about the business); this one decides whether a model gets a system prompt, and
#: hard rule 5's sentences are in that prompt. So it is worth waiting longer for, and its
#: failure is a refusal rather than a degradation.
SESSION_FETCH_BUDGET_S: Final[float] = 3.0

#: How long a batch of turns or a settlement may take. Both run OFF the conversation's
#: critical path — nothing reads a turn while the call is running, and the settlement runs
#: after the pipeline has drained — so the bound is not about a caller waiting. It is about
#: not holding the drain open for ever against an API that accepted the connection and then
#: stopped talking: `PIPECAT_WORKER_DRAIN_GRACE_SECONDS` defaults to 20 s and a write that
#: outlasted it would be killed mid-flight anyway.
WRITE_BUDGET_S: Final[float] = 5.0

#: The routes, with `{…}` still to fill. Spelled once, here, so the two halves of this
#: product name one surface — `apps/api/worker/routes.py` mounts exactly these.
SESSION_PATH: Final[str] = "/v1/worker/session"
CALLS_PATH: Final[str] = "/v1/worker/calls"

#: The ref `probe()` presents. It is deliberately NOT a valid `pipecat:<uuid>:<uuid>`, so it
#: can never name a real agent of any tenant — what the probe wants back is a REFUSAL, and
#: the one it wants is 404 rather than 401. See `probe`.
PROBE_REF: Final[str] = "preflight"


class WorkerApiError(RuntimeError):
    """The API could not answer, or answered something this worker cannot use.

    RAISED and not degraded, unlike `memory.ApiCallerMemoryReader.recall`'s `()`. The
    difference is what is on the other side of the failure: a caller memory nobody can read
    is a nicety, and a session configuration nobody can read is a call that must not be
    answered — `config.AgentNotRunnableError`'s own reasoning, one hop further out.

    Carries no response body and no URL (hard rule 6): an error body quotes the request, and
    a request here carries a call ref.
    """


class WorkerApiClient:
    """`apps/api`, as the three calls one call makes. One client for the life of the process.

    **ONE `httpx.AsyncClient`, NOT ONE PER REQUEST**, for `memory.ApiCallerMemoryReader`'s
    measured reason: a client per request re-does DNS, TCP and TLS, and that handshake was
    roughly half of a measured round trip from this container. A container serves one call
    at a time and Pipecat Cloud reuses it across sessions (§8.2), so the second call on a
    warm container pays none of it.

    **THE CLIENT IS INJECTED AND THIS CLASS OWNS NO GLOBAL**, so a test owns its transport
    and opens no socket. `from_config` is the production constructor and is the only thing
    that builds one.
    """

    __slots__ = ("_base_url", "_client", "_owns_client", "_token")

    def __init__(self, *, client: httpx.AsyncClient, base_url: str, token: str) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._owns_client = False

    @classmethod
    def from_config(
        cls, *, base_url: str, token: str, transport: httpx.AsyncBaseTransport | None = None
    ) -> Self:
        """The production constructor: it opens the client and takes responsibility for it.

        `aclose()` then closes it, which is why `_owns_client` exists at all — a client this
        class did not open is one somebody else will close, and closing it here would pull
        the socket out from under them.

        **`transport` IS THE TEST SEAM AND IT IS ON THIS CONSTRUCTOR RATHER THAN A SECOND
        ONE.** `tests/worker_api_test.py` runs the real client against the real FastAPI app
        over `httpx.ASGITransport` — no socket, no mock, both halves of the contract really
        exercised — and it needs the ownership this method gives so the pool is closed when
        the test is done. Production passes nothing and gets httpx's own transport.
        """
        built = cls(client=httpx.AsyncClient(transport=transport), base_url=base_url, token=token)
        built._owns_client = True
        return built

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Release the connection pool, if this object opened it. Idempotent."""
        if self._owns_client:
            await self._client.aclose()

    # -- the three calls -----------------------------------------------------------------

    async def session(self, engine_agent_ref: str) -> WorkerSessionOut:
        """The published agent this call runs as. Raises `WorkerApiError` for every failure.

        **IT REFUSES RATHER THAN DEGRADING**, and that is hard rule 5 showing through the
        transport: the thing being read is the prompt that carries the truthful-answer floor
        and the agent's AI-disclosure sentence. A call assembled without it would put a live
        caller in front of a model running on whatever system message the vendor defaults
        to, which is the failure `config.AgentNotRunnableError` exists to prevent.
        """
        body = await self._request(
            "GET",
            f"{SESSION_PATH}/{engine_agent_ref}",
            budget_s=SESSION_FETCH_BUDGET_S,
            what="session",
        )
        return self._parse(WorkerSessionOut, body, what="session")

    async def post_observations(
        self, engine_call_id: str, batch: ObservationBatch
    ) -> ObservationsOut:
        """One batch of statuses and turns. Raises so the sink can keep them and retry."""
        body = await self._request(
            "POST",
            f"{CALLS_PATH}/{engine_call_id}/observations",
            budget_s=WRITE_BUDGET_S,
            what="observations",
            json=batch.model_dump(mode="json"),
        )
        return self._parse(ObservationsOut, body, what="observations")

    async def post_settlement(
        self, engine_call_id: str, request: SettlementRequest
    ) -> SettlementOut:
        """The terminal write. Raises, because a settlement nobody recorded must be loud."""
        body = await self._request(
            "POST",
            f"{CALLS_PATH}/{engine_call_id}/settlement",
            budget_s=WRITE_BUDGET_S,
            what="settlement",
            json=request.model_dump(mode="json"),
        )
        return self._parse(SettlementOut, body, what="settlement")

    async def probe(self) -> None:
        """Prove the API is reachable AND this container's token is good. Raises otherwise.

        **THIS IS WHAT `SELECT 1` USED TO BE, AND IT PROVES STRICTLY MORE.** A pool that has
        never connected is indistinguishable from a working one until the first checkout,
        which on this deployable is the first caller; the same is true of a base URL and a
        token nobody has presented. So the boot gate presents them, against a ref that
        cannot name any agent of any tenant.

        **404 IS THE PASS AND 401 IS THE FAILURE**, which is the whole design of the probe:
        the route checks the token BEFORE it parses the ref (`worker/routes._require_token`
        is the first line of the handler), so "not found" can only be reached by a caller
        that authenticated. Asking for a real agent would need an agent id this process does
        not have at boot, and would make readiness depend on somebody's published
        configuration.
        """
        response = await self._send("GET", f"{SESSION_PATH}/{PROBE_REF}", budget_s=WRITE_BUDGET_S)
        if response.status_code == httpx.codes.NOT_FOUND:
            return
        raise WorkerApiError(
            "the worker API did not answer the preflight probe with 404: it answered "
            f"{response.status_code}. 401 means this container's PIPECAT_WORKER_API_TOKEN is "
            "not the one the deployment installed; anything else means the base URL does "
            "not name this platform's API."
        )

    # -- internals -----------------------------------------------------------------------

    async def _send(self, method: str, path: str, *, budget_s: float, **kwargs: Any) -> Any:
        """One request, under a WALL-CLOCK bound, with the Bearer header. Never parses.

        TWO TIMERS, AND THEY MEASURE DIFFERENT THINGS — `memory.py` records the measurement
        this repeats. `httpx`'s `timeout=` is PER PHASE: connect, write, read and pool each
        get the value separately, so a request that spends the budget connecting and the
        budget again reading has honoured both and taken twice as long. `asyncio.timeout` is
        the only thing here that can keep a wall-clock promise; keeping the httpx value as
        well is what actually closes the socket rather than merely abandoning the coroutine
        holding it.
        """
        async with asyncio.timeout(budget_s):
            return await self._client.request(
                method,
                f"{self._base_url}{path}",
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=budget_s,
                **kwargs,
            )

    async def _request(
        self, method: str, path: str, *, budget_s: float, what: str, **kw: Any
    ) -> Any:
        """A 2xx body, or `WorkerApiError`. The one place a transport failure becomes ours.

        Broad and narrowed nowhere, for `memory.ApiCallerMemoryReader.recall`'s reason
        inverted: there every failure meant one thing to the caller and none could raise;
        here every failure means one thing too — this call's record did not reach us — and
        NONE may be swallowed. The TYPE is logged and the message is not: an error body
        quotes the request, and a request here carries the conversation.
        """
        try:
            response = await self._send(method, path, budget_s=budget_s, **kw)
            if response.status_code >= httpx.codes.BAD_REQUEST:
                # The STATUS, never the body. A problem+json detail from our own API is safe
                # prose, but a 502 from something in between is whatever it wants to be.
                raise WorkerApiError(
                    f"the worker API refused the {what} call: HTTP {response.status_code}"
                )
            return response.json()
        except WorkerApiError:
            raise
        except Exception as failure:
            logger.warning("worker api call failed", surface=what, reason=type(failure).__name__)
            raise WorkerApiError(
                f"the worker API could not be reached for the {what} call "
                f"({type(failure).__name__})"
            ) from failure

    @staticmethod
    def _parse(model: type[_Wire], body: Any, *, what: str) -> _Wire:
        """A 2xx body into its wire model, or `WorkerApiError`.

        Separate from the transport because "the API answered 200 with something else" is a
        different failure from "we never reached it" — a deploy of two halves built against
        different contracts, which is exactly what `calevate_shared.worker_api` exists to
        make impossible and this is the arm that notices if it ever happens anyway. The
        validation error is NOT carried into the message: Pydantic quotes the offending
        value, and on this wire the offending value can be a transcript.
        """
        try:
            return model.model_validate(body)
        except Exception as failure:
            raise WorkerApiError(
                f"the worker API answered the {what} call with a body this worker cannot "
                f"read ({type(failure).__name__}) — the two halves are built against "
                "different versions of calevate_shared.worker_api"
            ) from failure


__all__ = [
    "CALLS_PATH",
    "PROBE_REF",
    "SESSION_FETCH_BUDGET_S",
    "SESSION_PATH",
    "WRITE_BUDGET_S",
    "WorkerApiClient",
    "WorkerApiError",
]
