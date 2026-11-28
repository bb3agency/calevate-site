"""The API activity log's two jobs (W2.8, D-1047): move the request stream into
`api_requests` every minute, and delete what is past its 30 days once a day."""

from __future__ import annotations

from typing import Any, Final

from apps.api.core.logging import get_logger
from apps.api.public_api import activity

log = get_logger(__name__)

FLUSH_SECOND: Final = frozenset({40})
SWEEP_HOUR: Final = frozenset({4})  # IST: `settings.CRON_TIMEZONE` (D-709)
SWEEP_MINUTE: Final = frozenset({34})


async def flush_api_requests(ctx: dict[str, Any]) -> int:
    del ctx
    moved = await activity.flush()
    if moved:
        log.info("api_requests_flushed", extra={"rows": moved})
    return moved


async def sweep_api_requests(ctx: dict[str, Any]) -> int:
    del ctx
    removed = await activity.sweep_expired()
    log.info("api_requests_swept", extra={"rows": removed})
    return removed


__all__ = [
    "FLUSH_SECOND",
    "SWEEP_HOUR",
    "SWEEP_MINUTE",
    "flush_api_requests",
    "sweep_api_requests",
]
