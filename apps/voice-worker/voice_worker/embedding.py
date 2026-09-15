"""One question as a vector, on a live call. The only network call on the turn, and it is
bounded, optional, and fires on the turns the lexical arm already gave up on.

`knowledge.QueryEmbedder` is the Protocol — a question in, a vector or `None` out — and this
is its production implementation. It is a separate module from `knowledge.py` for the reason
`PackFetcher` and `storage.py` are separate from it: the index, the gate and the ranking are
pure and testable with no network, and the hosted encoder is the only part of the path that
can be slow, absent or down. The tests that prove the hybrid arm hand `SessionKnowledge` a
three-line fake and never open a socket.

**THE HOST IS NOT SPELLED HERE.** `calevate_shared.engine.google_openai_compat_base_url()`
is the one constructor in this tree that may name the Gemini Developer API, and
`scripts/check_model_residency.py` fails the build over a second literal. The route is
`POST <that base>/embeddings` with `Authorization: Bearer` — VERIFIED-LIVE from a container
on 14 Sep 2026, using the two-request discrimination `copilot/service.py` documents: the
body parser runs BEFORE the credential, so `{"zzz_not_a_param": true}` is refused by name
while a well-formed body fails only on the key ("Please pass a valid API key"). Both a
single-string and an array `input`, with and without `dimensions`, take the second path.

⚠ **WHAT IS NOT VERIFIED, STATED PLAINLY.** That the endpoint accepts the body is not proof
it honours `dimensions`, and nobody has run a turn through it from Pipecat Cloud `ap-south`.
The width is therefore re-checked on the way back rather than trusted, and `EMBED_BUDGET_S`
is an assumption with a measurement beside it rather than a finding — see its comment.

**HARD RULE 6.** The caller's question is conversation content. It is sent to the encoder,
which is the point, and it is never logged — not on success, not on a timeout, and above all
not inside a provider's error body, which quotes the request verbatim. Every log line here is
a count, a status code, a model name or an exception TYPE.

**HARD RULE 7, AND THE ONE THING THIS MODULE CANNOT DO ITSELF.** Every query vector is money.
This container is deliberately not the monolith (`storage.py` argues why) and so cannot reach
`billing/rates.llm_price_is_billable`, which is the ONE door to `unit_cost_paid`. So the
pre-flight is the CALLER's and it is structural rather than advisory: a `GeminiQueryEmbedder`
exists only where a bootstrap constructed one, `assemble_call` takes it as an argument
defaulting to `None`, and with `None` the dense arm never runs and not a paisa is spent. What
the bootstrap must ask before constructing one is the same question
`apps/api/kb/pack_vectors.pack_embedding_is_billable()` asks, of the same model id — and it
is worth saying why that is not a gap being waved past: a pack that carries vectors at all
was built by a deployment that had already answered it True at publish
(`pack_vectors.embed_entries` refuses to embed otherwise), so the dense arm is unreachable on
a deployment that never attested a price, whatever the bootstrap does. `tokens` travels back
on every result so the `NormalizedEventSink` writer meters what was bought rather than
re-deriving it from a character count.
"""

from __future__ import annotations

import asyncio
from typing import Any, Final

import httpx
from calevate_shared.engine import google_openai_compat_base_url
from loguru import logger

from voice_worker.knowledge import QueryVector

#: The model and the width, which must be the SAME PAIR the pack was built under or the
#: comparison is meaningless. They are not read from the pack because they are what this
#: process is CONFIGURED to buy; `SessionKnowledge` compares the two and refuses to run the
#: arm when they disagree, which is the check that actually protects the ranking.
#: Both are `apps/api/kb/pack_vectors`' constants, restated here rather than imported because
#: this container must not import the monolith — and pinned together by
#: `tests/voice_worker_hybrid_test.py`, so a change on one side is a red test and not a
#: quietly mismatched encoder.
EMBEDDING_MODEL: Final[str] = "models/gemini-embedding-001"
EMBEDDING_DIMS: Final[int] = 3072

#: Wall clock for the query embedding, and THE NUMBER THAT KEEPS A TURN HONEST.
#:
#: ⚠ **AN ASSUMPTION WITH A MEASUREMENT BESIDE IT, NOT A FINDING.** Measured from THIS
#: container on 14 Sep 2026 (through an egress proxy, not from Pipecat Cloud `ap-south`, and
#: against an INVALID key so no inference ran): five POSTs to the live route, total
#: 0.24-0.51 s including TLS, ~0.16 s once a connection was warm. A real request does actual
#: encoder work on top of that and crosses a different network, so the true figure is larger
#: and is UNKNOWN until the first live call measures it (`pre-build-blockers` §3.6, the same
#: gap `storage.PACK_FETCH_BUDGET_S` records).
#:
#: **WHY IT IS BELOW `pipeline.FUNCTION_CALL_TIMEOUT_SECS` (2.0 s) RATHER THAN EQUAL TO IT.**
#: That constant is how long the LLM leg waits for a tool handler before giving up. If this
#: budget were the same number, an embedder that hung would burn the tool's entire allowance
#: and the model would get "the function failed and returned no result" — no outcome word, no
#: guidance, and an agent free to answer from its own priors about a client's business. Below
#: it, a hung encoder returns `temporarily_unavailable` INSIDE the tool call and the agent
#: says it cannot check right now, which is hard rule 5's posture applied to the client's
#: facts. 1.2 s leaves ~0.8 s for the lexical pass (~0.5 ms), the cosine scan and the
#: handler, which is not tight.
#:
#: **AND WHY THE TURN IS ALLOWED TO GROW AT ALL.** The arm fires ONLY where the lexical arm
#: answered `not_found` or `ambiguous` — turns whose alternative outcome is the agent saying
#: it has no information. Spending a second to turn 2 hits in 24 into 23
#: (`knowledge.py`'s module docstring has the table) is a trade made on the turns that were
#: already lost, and never on the ~0.5 ms `found` path.
EMBED_BUDGET_S: Final[float] = 1.2


class GeminiQueryEmbedder:
    """`knowledge.QueryEmbedder` over the Gemini OpenAI-compat surface. Structurally typed.

    It does not inherit the Protocol and does not need to — a class with the right `embed`
    satisfies it, which is the property the Protocol was introduced for
    (`storage.ObjectStorePackFetcher` says the same of `PackFetcher`).

    **ONE `httpx.AsyncClient` FOR THE LIFE OF THE PROCESS, NOT ONE PER TURN.** A client per
    request re-does DNS, TCP and the TLS handshake every time, and the measurement above puts
    the handshake at roughly half the round trip (0.35 s of a 0.51 s first call against 0.08 s
    once warm). On a budget this size that is the difference between an arm that answers and
    one that times out. The client is injected rather than constructed here so a test owns its
    transport and this class owns no global.
    """

    __slots__ = ("_api_key", "_budget_s", "_client", "_dimensions", "_model")

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        api_key: str,
        model: str = EMBEDDING_MODEL,
        dimensions: int = EMBEDDING_DIMS,
        budget_s: float = EMBED_BUDGET_S,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._model = model
        self._dimensions = dimensions
        self._budget_s = budget_s

    @property
    def model(self) -> str:
        """Which encoder this process buys from. Compared against the pack's declaration
        before the arm runs — two models' vectors are not comparable, and the failure would
        be a confident wrong ranking rather than an error."""
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, question: str) -> QueryVector | None:
        """One question as a vector, or `None` for every way that can fail. NEVER RAISES.

        `None` is not an error channel being abused — it is the honest answer to "did we get
        a vector?", and `SessionKnowledge` turns it into `temporarily_unavailable`, which is
        the word for "we could not look" as distinct from "they do not publish that". An
        exception instead would cross into `pipeline._search`, where hard rule 5's posture
        would be replaced by a tool that "failed and returned no result".

        The width is CHECKED rather than trusted: `dimensions` is sent, the endpoint accepts
        the field (VERIFIED-LIVE), and whether it honours it is not proven from here — so a
        row at another width is refused rather than compared against passage vectors it
        cannot be compared with.
        """
        try:
            # TWO TIMERS, MEASURING DIFFERENT THINGS. `httpx`'s `timeout=` is PER PHASE —
            # connect, write, read and pool each get the value separately — so a request
            # that spends the budget connecting and the budget again reading has honoured
            # it and taken 2x `EMBED_BUDGET_S`, which is `FUNCTION_CALL_TIMEOUT_SECS` gone
            # and the model told only that "the function failed and returned no result".
            # The budget's whole argument is a WALL CLOCK inside the tool call, and
            # `asyncio.timeout` is the only thing here that keeps one. Same pair, same
            # reason, as `memory.ApiCallerMemoryReader.recall`: the httpx value stays
            # because it is what closes the socket rather than merely abandoning the
            # coroutine holding it.
            async with asyncio.timeout(self._budget_s):
                response = await self._client.post(
                    f"{google_openai_compat_base_url()}/embeddings",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "input": question,
                        "dimensions": self._dimensions,
                    },
                    timeout=self._budget_s,
                )
                response.raise_for_status()
                body = response.json()
        # Broad and narrowed nowhere: a timeout, a refused connection, a 5xx, a 401 on a
        # rotated key and a body that is not JSON all mean the same thing to the caller — we
        # did not get a vector — and none of them may reach the pipeline as an exception. The
        # TYPE is logged and the message is not: a provider's error body quotes the request,
        # and the request is the caller's own words (hard rule 6).
        except Exception as failure:
            logger.warning("query embedding failed", reason=type(failure).__name__)
            return None
        return self._vector_of(body)

    def _vector_of(self, body: Any) -> QueryVector | None:
        """The first embedding out of a 2xx body, or `None` for a shape this API does not have.

        Separate from `embed` so the wire-shape handling is exercised without a transport, and
        because "the provider answered 200 with something else" is a different failure from
        "we never reached it" even though both answer the caller the same way.
        """
        if not isinstance(body, dict):
            logger.warning("query embedding shape", reason="not_an_object")
            return None
        rows = body.get("data")
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            logger.warning("query embedding shape", reason="no_data")
            return None
        values = rows[0].get("embedding")
        if not isinstance(values, list) or len(values) != self._dimensions:
            logger.warning(
                "query embedding width",
                want=self._dimensions,
                got=len(values) if isinstance(values, list) else None,
            )
            return None
        usage = body.get("usage")
        tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        return QueryVector(
            values=tuple(float(value) for value in values),
            tokens=tokens if isinstance(tokens, int) else None,
        )


__all__ = [
    "EMBEDDING_DIMS",
    "EMBEDDING_MODEL",
    "EMBED_BUDGET_S",
    "GeminiQueryEmbedder",
    "QueryVector",
]
