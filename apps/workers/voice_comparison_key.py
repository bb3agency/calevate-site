"""Our Sarvam voice key, re-installed in the voice-comparison workspace when it is rotated
(D-946). Enqueued through the outbox by `ops/secret_routes.set_secret_route` in the
transaction that stores the new version.

Only that one workspace holds the key (`ops/voice_comparison`), so there is no fan-out. A
deployment that never set the comparison up has nothing to push. No client is affected by a
failure: the comparison page would speak on the previous key, or not at all once it is
revoked, so the alarm asks for attention rather than paging.
"""

from __future__ import annotations

from typing import Any, Final

from arq import Retry
from calevate_shared.backoff import ladder_delay_s

from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES, job_try
from apps.api.core.settings import get_settings
from apps.api.db.session import untenanted_session
from apps.api.ops.secret_service import resolve_secrets
from apps.api.ops.voice_comparison import SARVAM_VOICE_SECRET, find_voice_lab, install_sarvam_key
from apps.workers.studio_voice_key import hosting_engine

log = get_logger(__name__)

_RETRY_AFTER_S: Final = (30, 120, 600)


async def _current_key() -> str | None:
    """The newest stored version, read from the store rather than this process's settings,
    which may not have re-read it yet."""
    async with untenanted_session() as session:
        resolved = await resolve_secrets(session)
    return resolved.values.get(SARVAM_VOICE_SECRET) or get_settings().sarvam_voice_api_key


async def push_voice_comparison_key(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    del payload  # the store holds the key; the payload only names the version
    engine = hosting_engine()
    if engine is None:
        return "not_hosted"
    key = await _current_key()
    if not key:
        return "no_key"
    try:
        workspace = await find_voice_lab()
        if workspace is None:
            return "no_workspace"
        await install_sarvam_key(engine, workspace, key)
    except ProblemError as exc:
        permanent = exc.kind in ("validation", "business_rule")
        if not permanent and job_try(ctx) < WORKER_MAX_TRIES:
            raise Retry(defer=ladder_delay_s(_RETRY_AFTER_S, job_try(ctx))) from exc
        log.warning("voice_comparison_key_push_failed", extra={"reason": exc.code})
        alert(
            "CORE_LOGIC",
            "voice_comparison_key_push_failed",
            detail=(
                f"The rotated Sarvam voice key could not be installed in the voice-comparison "
                f"workspace ({exc.code}). No client is affected; the comparison page speaks "
                "Sarvam on the previous key until it is. Test the key in Settings, "
                "Credentials, then choose Set up Sarvam voices on the comparison page."
            ),
            reason=exc.code,
        )
        return "failed"
    log.info("voice_comparison_key_pushed")
    return "pushed"


__all__ = ["push_voice_comparison_key"]
