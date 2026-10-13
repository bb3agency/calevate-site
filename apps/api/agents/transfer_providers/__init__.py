"""Whether a live caller can be put through to a person on this engine, and what the
hand-over screen says about where that works."""

from apps.api.agents.transfer_providers.registry import (
    CARRIER_LIMITED_TRANSFER_NOTES,
    NOT_OUR_CARRIER_LEG,
    PLATFORM_CANNOT_TRANSFER,
    transfer_blocked_reason,
    transfer_platform_note,
)

__all__ = [
    "CARRIER_LIMITED_TRANSFER_NOTES",
    "NOT_OUR_CARRIER_LEG",
    "PLATFORM_CANNOT_TRANSFER",
    "transfer_blocked_reason",
    "transfer_platform_note",
]
