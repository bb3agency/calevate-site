"""What our own voice provider says about its health (D-987), in our words.

The Studio rung speaks on our Cartesia key, and the voice platform has no backup voice on
our keys, so when a Studio call goes silent the first question is whether Cartesia itself
is failing. Cartesia publishes a public Statuspage summary, read here with no key; its
shape stays in this module (hard rule 2) and the healer reads only `VoiceProviderStatus`.

VERIFIED-VENDOR-PAGE: `GET https://status.cartesia.ai/api/v2/summary.json` answered on
13 Nov 2026 with `{"status": {"indicator": "none", "description": "All Systems
Operational"}, "components": [{"name": "Text to Speech (US)", "status": "operational"},
...]}`. Statuspage's indicator is one of `none`, `minor`, `major`, `critical`; anything
else, or no answer, is read as unknown, never as healthy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import httpx

from apps.api.core.logging import get_logger

log = get_logger(__name__)

CARTESIA_STATUS_URL: Final = "https://status.cartesia.ai/api/v2/summary.json"
#: A status read is advice beside our own evidence; it must never hold a healer tick.
STATUS_TIMEOUT_S: Final = 3.0
#: Statuspage indicators that say speech is degraded or down.
_DEGRADED: Final = frozenset({"major", "critical"})
_KNOWN: Final = frozenset({"none", "minor", "major", "critical"})


@dataclass(frozen=True, slots=True)
class VoiceProviderStatus:
    """Our voice provider's own reading. `operational` is None when it could not be read."""

    reachable: bool
    operational: bool | None = None
    #: Its indicator, one of Statuspage's four words, for the operator's line.
    indicator: str | None = None

    def words(self) -> str:
        if not self.reachable or self.operational is None:
            return "the voice provider's status page did not answer"
        if self.operational:
            return f"the voice provider reports itself working ({self.indicator})"
        return f"the voice provider reports a fault ({self.indicator})"


def read_summary(body: object) -> VoiceProviderStatus:
    """A Statuspage summary body in our words."""
    if not isinstance(body, dict):
        return VoiceProviderStatus(reachable=False)
    status = body.get("status")
    indicator = status.get("indicator") if isinstance(status, dict) else None
    if indicator not in _KNOWN:
        return VoiceProviderStatus(reachable=True)
    return VoiceProviderStatus(
        reachable=True, operational=indicator not in _DEGRADED, indicator=str(indicator)
    )


async def own_voice_provider_status(
    transport: httpx.AsyncBaseTransport | None = None,
) -> VoiceProviderStatus:
    """Cartesia's own status. Never raises: an unreadable page is `reachable=False`."""
    try:
        async with httpx.AsyncClient(timeout=STATUS_TIMEOUT_S, transport=transport) as client:
            response = await client.get(CARTESIA_STATUS_URL)
        body = response.json() if response.status_code == 200 else None
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("voice_provider_status_unreadable", extra={"error": type(exc).__name__})
        body = None
    return read_summary(body)


__all__ = [
    "CARTESIA_STATUS_URL",
    "VoiceProviderStatus",
    "own_voice_provider_status",
    "read_summary",
]
