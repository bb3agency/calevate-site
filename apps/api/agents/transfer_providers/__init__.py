"""Putting a live caller through to a person, on an engine whose carrier leg is ours.

The public surface is the Protocol, our outcome vocabulary and the one selector. Nothing
outside this package imports an adapter module directly — that is the property that makes
a second carrier a one-file change, and it is the boundary `apps.api.engine`'s factory
holds for the voice engine and `compliance/kyc_providers` for the verification vendor.
"""

from apps.api.agents.transfer_providers.base import (
    HANDOFF_OUTCOME_OF,
    TRANSFER_PROVIDERS,
    CallTransferProvider,
    TransferContractUnverifiedError,
    TransferOutcome,
    TransferRefusedError,
    TransferRequest,
    TransferStarted,
)
from apps.api.agents.transfer_providers.registry import (
    NOT_OUR_CARRIER_LEG,
    PLATFORM_CANNOT_TRANSFER,
    PROVIDER_CONTRACT_UNVERIFIED,
    PROVIDER_NOT_LICENSED,
    TransferCapability,
    available_transfer,
    transfer_blocked_reason,
)

__all__ = [
    "HANDOFF_OUTCOME_OF",
    "NOT_OUR_CARRIER_LEG",
    "PLATFORM_CANNOT_TRANSFER",
    "PROVIDER_CONTRACT_UNVERIFIED",
    "PROVIDER_NOT_LICENSED",
    "TRANSFER_PROVIDERS",
    "CallTransferProvider",
    "TransferCapability",
    "TransferContractUnverifiedError",
    "TransferOutcome",
    "TransferRefusedError",
    "TransferRequest",
    "TransferStarted",
    "available_transfer",
    "transfer_blocked_reason",
]
