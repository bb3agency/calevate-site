"""The object store, as the one thing this worker fetches from it: a knowledge pack.

`knowledge.PackFetcher` is the Protocol — an object key in, bytes out — and this is its
production implementation. It is a separate module from `knowledge.py` for the reason that
Protocol exists at all: the search, the index and the cache are pure and testable with no
network, and the S3 client is the only part of the path that can be slow, absent or down.

**WHY THIS IS NOT `apps/workers/storage.py`, WHICH ALREADY TALKS TO THIS BUCKET.** That
module is the monolith's: it imports `apps.api.core.settings`, `apps.api.core.logging` and
`apps.api.integrations.egress_guard`, and it carries recordings, webhook bodies, carrier
paperwork and the KB uploads. This is a different deployable — Pipecat Cloud `ap-south`,
box 1 of `docs/PIPECAT-MIGRATION.md` §8 — whose whole dependency argument is that it does
NOT carry the monolith into a voice container. So the duplication is one boto3 client
builder, deliberately, and the parts of its reasoning that are load-bearing are cited
below rather than re-derived. `store_knowledge_pack` (the writer) stays over there with
the publish path that calls it; this is the reader, and the two share the key builder that
actually matters, `calevate_shared.knowledge_pack.pack_object_key`.

**HARD RULE 6.** An object key names the tenant, the agent and the content hash of that
client's approved knowledge. Nothing here logs a key, and nothing here logs a store's own
error body, which quotes one.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Final

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from loguru import logger

#: How long the session start may wait on object storage before the call is assembled
#: without its knowledge base.
#:
#: ⚠ **AN ASSUMPTION, NOT A MEASUREMENT, AND IT IS STATED AS ONE.** This repository
#: declares no PRE-ANSWER budget at all: `calevate_shared.engine.LATENCY_BUDGET` is
#: endpointing + turn + retrieval, all of it INSIDE a connected call, and nobody has timed
#: a pack fetch from a Pipecat Cloud `ap-south` container to our R2 bucket — that is a
#: measurement to take on the first real call (`pre-build-blockers` §3.6), and what
#: replaces this comment.
#:
#: **WHY THERE IS A BOUND AT ALL**, which does not depend on the number: without one, a
#: store that accepts the connection and then stops talking holds the session in assembly
#: for as long as the socket lives, and the caller hears ringing that never becomes a
#: conversation. With one, the worst case is an agent that answers on time and says it
#: cannot verify something right now — hard rule 5's posture, extended to the client's
#: facts, which is exactly what `load_session_knowledge` already does with every other way
#: this can fail.
#:
#: **WHY 2.0 RATHER THAN A NUMBER OF ITS OWN.** It is `pipeline.FUNCTION_CALL_TIMEOUT_SECS`,
#: this worker's one existing statement of how long it waits on an HTTP call of ours before
#: silence is worse than an honest refusal. Two numbers for one question is the drift the
#: quality bar refuses, and a second one invented here would be no better measured.
PACK_FETCH_BUDGET_S: Final[float] = 2.0

#: Bucket and endpoint, read from the process environment under the spelling every deploy
#: already uses (`.env.example`, `OBJECT_STORE_BUCKET` / `OBJECT_STORE_ENDPOINT`). Named
#: here rather than typed at each call site so a rename is one edit and a typo is one
#: failure, not a silent read of `None`.
BUCKET_ENV: Final[str] = "OBJECT_STORE_BUCKET"
ENDPOINT_ENV: Final[str] = "OBJECT_STORE_ENDPOINT"

#: The codes S3 uses for "that object is not there". Absent is a different fact from
#: unreachable and the two must not merge: `knowledge.load_session_knowledge` answers
#: `absent` to one and `fetch_failed` to the other, and only one of them should page
#: anybody. Same set as `apps/workers/storage.read_kb_object`, which is the same question
#: asked of the same store.
_MISSING_CODES: Final[frozenset[str]] = frozenset({"NoSuchKey", "NoSuchBucket", "404", "NotFound"})


class ObjectStoreNotConfiguredError(RuntimeError):
    """The container has no bucket to read. A deploy fault, and it fails at construction.

    Raised where the fetcher is BUILT rather than where a pack is fetched, so a
    misconfigured container is a startup failure somebody sees instead of every call on it
    quietly answering `temporarily_unavailable` for the life of the deploy.
    """


def _client(endpoint: str) -> Any:
    """The S3 client for this container.

    **`boto3.Session().client(...)`, never the module-level `boto3.client(...)`**, and
    **the region is explicit** — both for the reasons `apps/workers/storage._client`
    argues at length and neither of which is about that module: the module-level helper
    reuses a process-global session, so the first caller anywhere fixes the credentials
    every later caller signs with; and botocore silently scopes an s3 signature to
    `us-east-1` when nothing supplies a region, which is not a crash, it is a signature
    against a region nobody chose. `auto` is R2's documented value and is the CREDENTIAL
    SCOPE, not where the bytes live (D-450).

    **NOT CACHED, unlike that module's, and the difference is the call pattern.** There it
    is called per recording, per payload and synchronously from an API route, where the
    ~90 ms of building one was measured as event-loop CPU. Here it is called ONCE per
    container: `PackCache` means a warm container's second call fetches nothing at all, and
    a cache with one entry whose invalidation nobody needs is a global to get wrong later.

    **THE TIMEOUTS ARE THE REAL BOUND.** `asyncio.timeout` in `fetch` stops the AWAIT; only
    these stop the SOCKET, so without them a hung read would leave a thread holding a
    connection for the life of the process. `max_attempts=1` — no retry — because a retry
    inside a fixed wall-clock budget spends it twice and hands the caller the same silence;
    the pack is fetched once per session and the next session retries it anyway.
    """
    return boto3.Session().client(
        "s3",
        endpoint_url=endpoint,
        region_name=os.environ.get("AWS_REGION", "auto"),
        config=Config(
            signature_version="s3v4",
            connect_timeout=PACK_FETCH_BUDGET_S,
            read_timeout=PACK_FETCH_BUDGET_S,
            retries={"max_attempts": 1},
        ),
    )


class ObjectStorePackFetcher:
    """`knowledge.PackFetcher` over the S3-compatible object store. Structurally typed.

    It does not inherit the Protocol and does not need to: `PackFetcher` is a
    `typing.Protocol`, so a class with the right `fetch` satisfies it, and the tests that
    prove the four knowledge outcomes hand `load_session_knowledge` a two-line fake instead
    of this. That is the property the Protocol was introduced for.
    """

    __slots__ = ("_bucket", "_budget_s", "_client")

    def __init__(self, *, bucket: str, client: Any, budget_s: float = PACK_FETCH_BUDGET_S) -> None:
        self._bucket = bucket
        self._client = client
        self._budget_s = budget_s

    @classmethod
    def from_env(cls, *, budget_s: float = PACK_FETCH_BUDGET_S) -> ObjectStorePackFetcher:
        """Build one from the container's environment, or refuse with the variable's name."""
        bucket = os.environ.get(BUCKET_ENV, "").strip()
        endpoint = os.environ.get(ENDPOINT_ENV, "").strip()
        missing = [
            name for name, value in ((BUCKET_ENV, bucket), (ENDPOINT_ENV, endpoint)) if not value
        ]
        if missing:
            raise ObjectStoreNotConfiguredError(
                "the knowledge pack store is not configured: set " + ", ".join(missing)
            )
        return cls(bucket=bucket, client=_client(endpoint), budget_s=budget_s)

    async def fetch(self, object_key: str) -> bytes | None:
        """The pack's bytes, `None` when the object is not there, an exception when we could
        not look.

        Those three are three different facts and the caller turns each into a different
        state: `load_session_knowledge` answers `absent` to `None` and `fetch_failed` to a
        raise, and its own docstring is why neither reaches the pipeline as an exception.
        Collapsing the pair here — returning `None` on an outage — would tell an operator
        that a client had published nothing when in truth we could not reach the bucket.

        **BLOCKING WORK GOES TO A THREAD.** boto3 is synchronous and this runs on the
        asyncio loop that is about to carry a phone call; `asyncio.to_thread` is the same
        choice `apps/workers/storage` makes for the same client. The `asyncio.timeout`
        around it bounds the AWAIT and not the thread — a cancelled fetch leaves the thread
        to finish or to hit the socket timeouts in `_client`, which is why those exist and
        why the deadline here is a backstop rather than the only bound.
        """

        def _get() -> bytes:
            response = self._client.get_object(Bucket=self._bucket, Key=object_key)
            body: bytes = response["Body"].read()
            return body

        try:
            async with asyncio.timeout(self._budget_s):
                return await asyncio.to_thread(_get)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in _MISSING_CODES:
                return None
            # The CODE, never the exception's message: a store's error body quotes the key,
            # and the key names the tenant, the agent and the digest of their knowledge.
            logger.warning("knowledge pack fetch refused", reason=code or type(exc).__name__)
            raise
        except (BotoCoreError, TimeoutError) as exc:
            # `TimeoutError` is what `asyncio.timeout` raises on expiry, and it is reported
            # exactly like a transport failure because to the caller it is one: we did not
            # get the bytes, and we do not know whether the object is there.
            logger.warning("knowledge pack fetch failed", reason=type(exc).__name__)
            raise


__all__ = [
    "BUCKET_ENV",
    "ENDPOINT_ENV",
    "PACK_FETCH_BUDGET_S",
    "ObjectStoreNotConfiguredError",
    "ObjectStorePackFetcher",
]
