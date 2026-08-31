"""The thin cache tier (TRD §6's T1), and the reason it cannot serve a stale answer.

WHY A CACHE AT ALL. An SMB's callers ask the same handful of questions — hours, address, do
you take walk-ins, what does X cost — so the same normalised question recurs all day. TRD
§6.2's in-call budget is 100ms for the WHOLE round trip and D-109 measured our own server
half at p95 1.4ms single-flight, which leaves the budget to the network and the store; a
hit that never reaches the store is the only headroom this design can buy without knowing
who wins the D-28 bake-off.

**INVALIDATION IS THE HARD PART AND IT IS SOLVED STRUCTURALLY, NOT BY AN EVENT.** A stale
cached answer after an owner corrects their opening hours is a WRONG ANSWER ON A LIVE CALL.
An event-driven cache (publish → delete the keys) is correct only while every writer
remembers to fire the event; the failure is silent, unbounded, and lands on a caller. So
this cache is keyed on a STAMP of the knowledge it is caching — `RetrievalProvider.
knowledge_epoch`, which for T0 is the live prompt version, and a knowledge publish always
mints a new one (`agents/t0.py` INSERTS a version and repoints the agent; it never edits
one). A correction therefore moves every question onto a NEW key. Nothing has to be
deleted, nothing has to be remembered, and the entries under the old stamp are unreachable
the instant the stamp changes; they then expire on their own TTL.

The cost of that choice, stated plainly: the epoch read happens BEFORE the cache lookup, so
a hit is one small indexed Postgres read plus one Redis round trip, not a Redis round trip
alone. Both halves are measured in `tests/retrieval_latency_test.py` and reported
separately, because a provider whose own epoch is free would pay only the second.

The TTL is the SECOND line of defence and not the first: it bounds how long a stamp that
somehow failed to change can serve, and it bounds the memory a departed tenant occupies.

**TENANCY.** The tenant id is the first element of every key after the prefix, so a key is
addressable only by a caller that already holds that tenant id — and
`tests/retrieval_tenancy_test.py` proves two tenants asking the identical question in the
identical words compute two
different keys and cannot read each other's value. There is no shared or global entry in
this keyspace at all; that is not an optimisation left on the table, it is the property.

**PII.** A cache key is a durable, greppable string in a shared store, and a cached VALUE is
prose we will read back to somebody. So a question that `apps.workers.redaction.redact`
would change is REFUSED — not stripped, refused (`sanitize.assert_redacted`'s doctrine: a
guard that silently repairs its input teaches the caller nothing). A long digit run is
refused too, on a second ground: an order number or a policy number is caller-specific, so
caching it would be a key that can never be hit again anyway.
"""

from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from typing import Final
from uuid import UUID

from calevate_shared.retrieval import (
    Passage,
    RetrievalCapabilityName,
    RetrievalRequest,
    RetrievalResult,
    RetrievalTier,
)
from pydantic import BaseModel, ConfigDict
from redis.exceptions import RedisError

from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.workers.redaction import redact

log = get_logger(__name__)

#: The keyspace. Versioned in the prefix so a change to the VALUE shape (a new field on
#: `Passage`, say) is a new namespace rather than a decode error on every hit — the entries
#: under `v1` become unreachable and expire, which is the same mechanism the epoch uses.
#:
#: Its own prefix, shared with nothing: `invalidate_tenant` scans it, and a scan that could
#: match a rate-limit counter or an ARQ key would be an outage dressed as a cache flush.
KEY_PREFIX: Final = "retrieval:q:v1:"

#: Fifteen minutes. NOT the invalidation mechanism (the epoch is) — the ceiling on how long
#: a bug in the epoch could serve a wrong answer, and the reason a tenant who stops asking
#: stops occupying memory. Short enough that a stamp failure is an incident with a bounded
#: blast radius; long enough that a busy morning's twenty repeated questions are hits.
TTL_S: Final = 900

#: A digit run this long is a policy number, an order id or a phone number: caller-specific,
#: so it would never be hit twice, and exactly the shape that must not reach a durable key.
_MAX_DIGIT_RUN = 6
_LONG_DIGITS = re.compile(rf"\d{{{_MAX_DIGIT_RUN},}}")

#: Everything that is not a word character or whitespace, for normalisation.
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+", re.UNICODE)


class QuestionNotCacheableError(Exception):
    """The question may not be turned into a cache key.

    A plain exception rather than a `ProblemError`: this is never a refusal a client sees.
    The retrieval still happens — it just is not cached — so the caller catches this and
    carries on. Carrying the reason so the log line says which guard fired.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def normalise(question: str) -> str:
    """The cache's idea of "the same question", and the PII gate on the way in.

    NFKC first (so a full-width or composed form is one question, not two), then casefold,
    then punctuation out, then whitespace collapsed. Deliberately NO stemming, NO synonym
    expansion and NO embedding: this is a NORMALISED-KEY cache, and every one of those
    would make two different questions share an answer, which on a live call is how "do you
    take walk-ins?" gets answered with the price list. The semantic reach of this tier is
    exactly "the same question, typed differently", which is what an SMB's repeat callers
    actually produce.

    Raises `QuestionNotCacheableError` when the question carries anything personal.
    """
    result = redact(question)
    if result.changed:
        # Not stripped — refused. The kinds, never the text (hard rule 6).
        kinds = ",".join(sorted(set(result.kinds)))
        raise QuestionNotCacheableError(f"personal data in question: {kinds}")
    folded = unicodedata.normalize("NFKC", question).casefold()
    folded = _SPACE.sub(" ", _PUNCT.sub(" ", folded)).strip()
    if not folded:
        raise QuestionNotCacheableError("question normalises to nothing")
    if _LONG_DIGITS.search(folded):
        raise QuestionNotCacheableError("question carries a long digit run")
    return folded


def cache_key(request: RetrievalRequest, *, epoch: str) -> str:
    """`retrieval:q:v1:<tenant>:<agent|->:<tier>:<k>:<epoch>:<digest>`.

    THE TENANT IS FIRST AND IS NEVER HASHED, for two reasons that both matter: a key is
    addressable only by a caller that already holds the tenant id, and `invalidate_tenant`
    can scan one tenant's keys without touching another's.

    `tier` and `k` are in the key because they change the ANSWER: the same question asked at
    t0 and at t3 has two different right answers, and one cached under the other's key is a
    wrong answer with no symptom.

    The question is a SHA-256 digest, truncated to 32 hex characters, of the normalised
    text. Hashed rather than embedded because a question is client prose and a key is a
    thing operators grep, dump and screenshot; truncated because 128 bits is far past
    collision risk for a per-tenant, per-epoch keyspace that expires in fifteen minutes.
    """
    digest = hashlib.sha256(normalise(request.question).encode("utf-8")).hexdigest()[:32]
    agent = str(request.agent_id) if request.agent_id is not None else "-"
    return f"{KEY_PREFIX}{request.tenant_id}:{agent}:{request.tier}:{request.k}:{epoch}:{digest}"


class _CachedAnswer(BaseModel):
    """What is stored. The result MINUS the two fields that describe THIS call rather than
    the answer — `cached` and `elapsed_ms` — because storing them would replay one
    request's latency as another's and make every measurement below a lie."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    passages: tuple[Passage, ...]
    served_tier: RetrievalTier
    unmet_capability: RetrievalCapabilityName | None = None
    provider: str


async def get(request: RetrievalRequest, *, epoch: str) -> RetrievalResult | None:
    """A hit, or None. NEVER raises for a cache problem.

    A cache is not a system of record (BACKEND-PATTERNS §4, `core/redis.py`), so every
    failure mode here — Redis down, a value written by an older shape, a question that may
    not be keyed — degrades to a miss and a log line. The alternative, a 500 on the
    retrieval path because a cache was unwell, is the failure this whole tier exists to
    avoid.
    """
    started = time.perf_counter()
    try:
        raw = await get_redis().get(cache_key(request, epoch=epoch))
    except QuestionNotCacheableError as refused:
        log.info("retrieval_cache_unkeyable", extra={"reason": refused.reason})
        return None
    except RedisError as failure:
        log.warning("retrieval_cache_unavailable", extra={"error": type(failure).__name__})
        return None
    if raw is None:
        return None
    try:
        stored = _CachedAnswer.model_validate_json(raw)
    except ValueError:
        # A value this build cannot read. Treated as a miss rather than deleted: the write
        # below overwrites it anyway, and a delete here would be a second writer racing the
        # first for no gain.
        log.warning("retrieval_cache_undecodable")
        return None
    return RetrievalResult(
        passages=stored.passages,
        requested_tier=request.tier,
        served_tier=stored.served_tier,
        unmet_capability=stored.unmet_capability,
        provider=stored.provider,
        cached=True,
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
    )


async def put(request: RetrievalRequest, *, epoch: str, result: RetrievalResult) -> bool:
    """Store one answer under this tenant's keyspace. True if it was stored.

    **AN EMPTY RESULT IS NOT CACHED**, and that is a deliberate asymmetry. "We have nothing
    on file about refunds" is TRD §6's T4 condition, and the very next thing that happens is
    usually the client adding the missing knowledge — caching the miss would keep answering
    "we don't know" for a quarter of an hour after they fixed it. (The epoch would clear it
    on a KB publish, but not on the many other reasons a first search comes back empty.)

    A DEGRADED result (`unmet_capability` set) IS cached, with its flag intact, so the
    caller still discloses the degradation on a hit. Dropping the flag on the way through a
    cache is exactly the silent no-op the port forbids.
    """
    if result.is_empty():
        return False
    payload = _CachedAnswer(
        passages=result.passages,
        served_tier=result.served_tier,
        unmet_capability=result.unmet_capability,
        provider=result.provider,
    )
    try:
        await get_redis().set(cache_key(request, epoch=epoch), payload.model_dump_json(), ex=TTL_S)
    except QuestionNotCacheableError as refused:
        log.info("retrieval_cache_unkeyable", extra={"reason": refused.reason})
        return False
    except RedisError as failure:
        log.warning("retrieval_cache_unavailable", extra={"error": type(failure).__name__})
        return False
    return True


async def invalidate_tenant(tenant_id: UUID) -> int:
    """Drop every cached answer for ONE tenant. Returns how many keys went.

    NOT the ordinary invalidation path — the epoch is, and it needs no caller. This exists
    for the two occasions where waiting for a stamp is not good enough: a DPDP erasure that
    must be able to say the cache holds nothing of theirs, and an operator who has to clear
    a bad answer NOW. It is scoped to one tenant by the key layout and cannot be widened by
    a caller.

    SCAN, never KEYS: `KEYS` blocks the server for the whole traversal, which on a shared
    Redis is an outage caused by a cleanup. Deleted in batches for the same reason.
    """
    redis = get_redis()
    removed = 0
    try:
        async for key in redis.scan_iter(match=f"{KEY_PREFIX}{tenant_id}:*", count=200):
            removed += int(await redis.delete(key))
    except RedisError as failure:
        log.warning("retrieval_cache_unavailable", extra={"error": type(failure).__name__})
        return removed
    log.info("retrieval_cache_invalidated", extra={"tenant_id": str(tenant_id), "keys": removed})
    return removed


__all__ = [
    "KEY_PREFIX",
    "TTL_S",
    "QuestionNotCacheableError",
    "cache_key",
    "get",
    "invalidate_tenant",
    "normalise",
    "put",
]
