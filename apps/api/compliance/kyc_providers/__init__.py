"""Client identity verification through a licensed aggregator (D-635).

The public surface is the Protocol, the four normalized facts and the one selector.
Nothing outside this package imports an adapter module directly — that is the property
that lets a second provider be a one-file change, and it is the same boundary
`apps.api.engine`'s factory holds for the voice engine.
"""

from apps.api.compliance.kyc_providers.base import (
    KYC_PROVIDERS,
    EntityBranch,
    IdentityVerificationProvider,
    ProviderContractUnverifiedError,
    VerificationOutcome,
    VerificationStart,
    entity_branch,
)
from apps.api.compliance.kyc_providers.registry import (
    NO_PROVIDER_CONFIGURED,
    NO_WEBHOOK_SECRET,
    PROVIDER_CONTRACT_UNVERIFIED,
    PROVIDER_NOT_LICENSED,
    ProviderCapability,
    available_provider,
)

__all__ = [
    "KYC_PROVIDERS",
    "NO_PROVIDER_CONFIGURED",
    "NO_WEBHOOK_SECRET",
    "PROVIDER_CONTRACT_UNVERIFIED",
    "PROVIDER_NOT_LICENSED",
    "EntityBranch",
    "IdentityVerificationProvider",
    "ProviderCapability",
    "ProviderContractUnverifiedError",
    "VerificationOutcome",
    "VerificationStart",
    "available_provider",
    "entity_branch",
]
