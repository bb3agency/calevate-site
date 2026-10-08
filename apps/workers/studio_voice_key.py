"""Push a rotated Cartesia key to the voice platform's workspace (D-688).

Studio voices speak on our Cartesia key installed in the ThinnestAI workspace (`PUT
/byok/credentials`, kind `tts`). When an operator installs or rotates `cartesia_api_key` in
the ops console, the platform must hold the new key too, or Studio calls keep speaking on the
old one until it is revoked and then do not speak at all: there is no fallback to the
platform's own voices (`thinnest-findings/mirror/snapshots/2026-10-07b/pages/api-reference/
bring-your-own-keys.md:100-103`). Replacing a key for the same provider keeps its model
(LIVE-DOCS `docs.thinnest.ai/api-reference/bring-your-own-keys`, read 8 Oct 2026), so nothing
but the key is sent.

Enqueued through the outbox by `ops/secret_routes.set_secret_route` in the transaction that
stores the new version. It reads the key from the store itself rather than from this process's
settings, which may not have re-read it yet. IDEMPOTENT: pushing the same key twice stores the
same key. Nothing is pushed while the workspace holds no Cartesia voice key: switching Studio
voices on installs it (`agents/studio_voices.enable_studio_voices`). The key is never logged.
"""

from __future__ import annotations

from typing import Any, Final

from apps.api.agents.hosted_voices import STUDIO_VOICE_PROVIDER
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.session import untenanted_session
from apps.api.engine import get_engine
from apps.api.engine.catalogue import HostsVoices
from apps.api.ops.secret_service import resolve_secrets

log = get_logger(__name__)

#: The secret whose rotation this follows.
CARTESIA_KEY: Final = "cartesia_api_key"


async def _current_key() -> str | None:
    """The newest stored version, or the environment's value when the environment declares
    it (the store skips a key the environment shadows)."""
    async with untenanted_session() as session:
        resolved = await resolve_secrets(session)
    return resolved.values.get(CARTESIA_KEY) or get_settings().cartesia_api_key


async def push_studio_voice_key(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Replace the workspace's Cartesia voice key with ours. Returns what it did."""
    del ctx, payload  # the store holds the key; the payload only names the version
    engine = get_engine()
    if not isinstance(engine, HostsVoices) or engine.capabilities.is_ours("tts"):
        return "not_hosted"
    state = await engine.own_key_state()
    if state.voice_provider != STUDIO_VOICE_PROVIDER:
        return "no_studio_key"
    key = await _current_key()
    if not key:
        return "no_key"
    try:
        await engine.install_own_voice_key(provider=STUDIO_VOICE_PROVIDER, api_key=key, model=None)
    except ProblemError as exc:
        log.warning("studio_voice_key_push_failed", extra={"reason": exc.code})
        alert(
            "CORE_LOGIC",
            "studio_voice_key_push_failed",
            detail=(
                "The rotated Cartesia key could not be installed in the voice platform "
                f"workspace ({exc.code}), so Studio calls still speak on the previous key. "
                "Test the key from the ops console Secrets panel, then save it "
                "again in the ops console, which retries the push."
            ),
            reason=exc.code,
        )
        return "failed"
    log.info("studio_voice_key_pushed", extra={"engine": engine.name})
    return "pushed"


__all__ = ["CARTESIA_KEY", "push_studio_voice_key"]
