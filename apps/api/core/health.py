"""Health & readiness — three endpoints, ONE word for the dashboard.

BACKEND-PATTERNS §6:
- `/healthz/live`   — process is up. Touches NO dependency (a DB blip must not get
                      the container killed by the orchestrator).
- `/healthz`        — DB SELECT 1 + Redis PING. 503 problem+json when degraded.
- `/healthz/ready`  — adds queue depth + oldest-waiting age (stale-worker detection)
                      and `runtime_config_missing_keys`. This is the GO-LIVE GATE that
                      tolerant worker boot defers to.

`degradation_mode` is priority-ordered so a dashboard shows one word:
db_down > redis_down > queue_stale > config_missing > none.

═══ THE STATUS IS PUBLIC. THE DETAIL IS NOT. ═══

`/healthz/ready` used to publish, to anyone who asked, the NAMES of the configuration
keys this deployment has not installed yet — `fields[].field` is
`runtime_config_missing_keys`, i.e. `BOLNA_API_KEY`, `CLERK_ADMIN_SECRET_KEY`,
`AUDIT_CHAIN_SECRET` — plus which of DB/Redis is down and how far behind the job queue
is. Unauthenticated, exempt from the in-app rate limiter, and proxied from
`api.calevate.tech` by `infra/nginx/calevate.conf.template`. That is a targeting oracle:
it tells a stranger which credentials are NOT installed, and it is loudest during
exactly the window before the real keys land.

The origin lock (`infra/nginx/snippets/calevate-origin.conf`) is not the answer and
never was: it is already included by the api vhost, and what it admits is every
Cloudflare edge address — i.e. the whole internet, because the zone is proxied. It
stops a direct-to-IP scan; it does not stop `curl https://api.calevate.tech/healthz/ready`.

So the split is:

- **status code and status word stay public.** A probe reads them and a probe that
  cannot distinguish healthy from not is worse than no probe at all. `compose.prod.yml`
  polls `/healthz/live`, `scripts/vps-deploy.sh` polls `/healthz` — neither can carry a
  credential, and neither reads a body.
- **everything that names an internal fact is disclosed only to `ops:manage`**, through
  the one permission ladder this repo already has (`core.auth.requires`), injected as
  `detail_gate` by the composition root.
- **and when it is withheld it is LOGGED instead**, so the operator whose next step it
  is still has it. A withheld detail with no operator-reachable copy would be a
  security fix that costs an outage its diagnosis.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from sqlalchemy import text

from apps.api.core.errors import PROBLEM_CONTENT_TYPE
from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings, runtime_config_missing_keys
from apps.api.db.session import untenanted_session

log = get_logger(__name__)

DegradationMode = Literal["db_down", "redis_down", "queue_stale", "config_missing", "none"]

# A job waiting longer than this means no worker is draining the queue.
QUEUE_STALE_AFTER_S = 120.0
ARQ_QUEUE_KEY = "arq:queue"

#: Answers, for ONE request, "may this caller be told WHY this service is unhealthy?".
#:
#: INJECTED RATHER THAN IMPORTED, and both halves of the reason are load-bearing:
#:  - `core.auth` is outside voice-runtime's pinned import surface
#:    (`tests/voice_runtime_import_surface_test.py`) and this module is inside it. An
#:    `import` here would put the Clerk verifier and its JWKS client on the boot graph
#:    of the service carrying live calls, to answer a question that service has no
#:    authentication layer to ask (hard rule 3).
#:  - it keeps "what counts as authorised" in the composition root (`core.bootstrap`)
#:    rather than growing a second auth decision inside a probe.
HealthDetailGate = Callable[[Request], Awaitable[bool]]


#: How long any single dependency probe may take before it IS the answer (D-182).
#:
#: A HEALTH ENDPOINT THAT HANGS IS WORSE THAN ONE THAT FAILS. This was the only wait in
#: the repo with no bound: `SELECT 1` through `untenanted_session()` with no statement
#: timeout, no connect timeout, and `pool_pre_ping`'s own `SELECT 1` hanging on the very
#: same socket (`apps/voice-runtime/webhook_routes.py` states that pairing outright). A
#: blackholed Postgres — dropped NAT mapping, firewall change, a host that stops answering
#: without an RST — therefore made `/healthz/ready` block for ever instead of returning
#: `503 db_down`, which is the one word it exists to produce, and every hung probe held a
#: pooled connection for the life of the request.
#:
#: TWO SECONDS, and the number is chosen against its callers rather than picked: the two
#: probes run in sequence, so `/healthz` answers in under 4s inside `vps-deploy.sh`'s
#: `curl --max-time 5` and inside the compose healthcheck's `timeout: 5s`. It is the same
#: bound voice-runtime already puts on its durable work (`_DURABLE_DEADLINE_S`), and it is
#: deliberately UNDER `db.session._POOL_TIMEOUT_S` (5s): a probe that waited out the pool
#: queue would report the database as healthy while no caller could reach it.
_PROBE_BUDGET_S = 2.0


async def _check_db() -> bool:
    try:
        async with asyncio.timeout(_PROBE_BUDGET_S), untenanted_session() as session:
            await session.execute(text("SELECT 1"))
        return True
    except TimeoutError:
        # NOT an exception to the caller: "the database did not answer in two seconds" is
        # the same operational fact as "the database refused", and the orchestrator can
        # act on `db_down` where it cannot act on a request that never returns.
        log.warning("health_db_timeout", extra={"budget_s": _PROBE_BUDGET_S})
        return False
    except Exception:
        log.warning("health_db_unavailable")
        return False


async def _check_redis() -> bool:
    try:
        async with asyncio.timeout(_PROBE_BUDGET_S):
            return bool(await get_redis().ping())
    except TimeoutError:
        # Belt and braces over `core/redis.py`'s `socket_timeout=2`: that bounds one
        # socket operation, and a resolver that never answers is not one.
        log.warning("health_redis_timeout", extra={"budget_s": _PROBE_BUDGET_S})
        return False
    except Exception:
        log.warning("health_redis_unavailable")
        return False


async def _queue_stats() -> tuple[int, float | None]:
    """(depth, oldest_waiting_seconds). ARQ scores its queue zset with the run-at
    timestamp in ms, so the minimum score is the oldest ready job.

    Bounded by its CALLER (`ready`), which treats a breach as `redis_down` — the same
    verdict a refused connection gets, and for the same reason.
    """
    redis = get_redis()
    depth = int(await redis.zcard(ARQ_QUEUE_KEY))
    if depth == 0:
        return 0, None
    oldest = await redis.zrange(ARQ_QUEUE_KEY, 0, 0, withscores=True)
    if not oldest:
        return depth, None
    score_ms = float(oldest[0][1])
    return depth, max(0.0, time.time() - score_ms / 1000.0)


def build_health_router(service: str, *, detail_gate: HealthDetailGate | None = None) -> APIRouter:
    """Same three endpoints for api, voice-runtime and (via a tiny shim) workers.

    `detail_gate` decides who is told the detail. Absent — which is voice-runtime, and
    is not an oversight — NOBODY is: that service authenticates no human being, and
    `hooks.calevate.tech/healthz/ready` published the same key names from the same
    `runtime_config_missing_keys` call. Its operators read the log line instead, which
    is where they already are when a webhook receiver is unhealthy.
    """
    router = APIRouter(tags=["health"])

    async def _detail_allowed(request: Request) -> bool:
        return detail_gate is not None and await detail_gate(request)

    @router.get("/healthz/live", summary="Liveness — touches no dependency")
    async def live() -> dict[str, str]:
        return {"status": "ok", "service": service}

    @router.get("/healthz", summary="Health — DB + Redis")
    async def health(request: Request, response: Response) -> dict[str, Any]:
        db_ok = await _check_db()
        redis_ok = await _check_redis()
        mode: DegradationMode = "db_down" if not db_ok else "redis_down" if not redis_ok else "none"
        body: dict[str, Any] = {
            "status": "ok" if mode == "none" else "degraded",
            "service": service,
        }
        if mode != "none":
            response.status_code = 503
            response.media_type = PROBLEM_CONTENT_TYPE
        # WHICH dependency is down is gated for the same reason `/healthz/ready`'s
        # fields[] is — it is a fact about our internals, and gating one while its
        # sibling published the identical `checks` dict would be a mitigation defeated
        # by a second URL. It needs no new log line: `_check_db`/`_check_redis` already
        # write one per failed probe, which is the operator's copy.
        if await _detail_allowed(request):
            body["degradation_mode"] = mode
            body["checks"] = {"db": db_ok, "redis": redis_ok}
        return body

    @router.get("/healthz/ready", summary="Readiness — the go-live gate")
    async def ready(request: Request, response: Response) -> dict[str, Any]:
        db_ok = await _check_db()
        redis_ok = await _check_redis()
        depth = 0
        oldest: float | None = None
        if redis_ok:
            try:
                async with asyncio.timeout(_PROBE_BUDGET_S):
                    depth, oldest = await _queue_stats()
            except Exception:
                # `TimeoutError` included, and folded in on purpose: a queue read that
                # does not finish and one that errors are the same readiness answer.
                redis_ok = False
        missing = runtime_config_missing_keys(get_settings())
        queue_stale = oldest is not None and oldest > QUEUE_STALE_AFTER_S

        mode: DegradationMode = (
            "db_down"
            if not db_ok
            else "redis_down"
            if not redis_ok
            else "queue_stale"
            if queue_stale
            else "config_missing"
            if missing
            else "none"
        )
        body: dict[str, Any] = {
            "status": "ready" if mode == "none" else "not_ready",
            "service": service,
        }
        if mode != "none":
            response.status_code = 503
            response.media_type = PROBLEM_CONTENT_TYPE
            # THE OPERATOR'S COPY. Unlike `/healthz`, nothing else logs any of this, so
            # withholding it from the response without writing it here would trade an
            # information leak for an undiagnosable red light. Key NAMES, never values:
            # `BOLNA_API_KEY` is the next step, and it is already in `.env.example`.
            # Joined into one string on purpose — `redact_mapping` renders a list extra
            # as "[N items]", which would log the count of what is missing and not the
            # names of it.
            log.warning(
                "health_not_ready",
                extra={
                    "service": service,
                    "degradation_mode": mode,
                    "queue_depth": depth,
                    "queue_oldest_waiting_s": oldest,
                    "missing_config_keys": ",".join(missing),
                },
            )
        if await _detail_allowed(request):
            body["degradation_mode"] = mode
            body["checks"] = {"db": db_ok, "redis": redis_ok}
            body["queue"] = {"depth": depth, "oldest_waiting_s": oldest}
            # Missing config renders as validation-style fields[] — one shape for
            # "something's not right" (§6).
            body["fields"] = [
                {"field": key, "rule": "required_for_readiness", "message": f"{key} is not set"}
                for key in missing
            ]
        return body

    return router


__all__ = [
    "QUEUE_STALE_AFTER_S",
    "DegradationMode",
    "HealthDetailGate",
    "build_health_router",
]
