"""Which provider this deployment may use, and the named reason when none may.

Two conditions, separate facts about separate things:

1. **A provider is configured** — `Settings.kyc_verification_provider` names a member of
   `KYC_PROVIDERS`. Unset is the default, and the client's screen then offers only the
   manual document review.
2. **Its credentials are installed**, in the ops console's encrypted path:
   * `cashfree` — `kyc_verification_client_id` and `kyc_verification_client_secret`. The
     client secret also signs Cashfree's webhooks, so there is no separate webhook secret.
   * `fake` — `kyc_verification_webhook_secret`, which signs the in-house adapter's
     deliveries.
   A receiver that cannot verify a signature must not exist: this feed marks a client
   VERIFIED, so an unverifiable one grants identity on anyone's say-so.

**ONE SELECTOR, ASKED BY EVERYONE.** The start route, the return route, the client's own
screen and the webhook all call this, so a screen can never offer a button the route
refuses. Whether a given tenant NEEDS a verification is `compliance.service`'s question and
is deliberately not asked here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from apps.api.compliance.kyc_providers.base import (
    KYC_PROVIDERS,
    IdentityVerificationProvider,
    ProviderContractUnverifiedError,
)
from apps.api.compliance.kyc_providers.cashfree import CashfreeDigiLocker
from apps.api.compliance.kyc_providers.fake import FakeIdentityProvider
from apps.api.compliance.kyc_providers.setu import SetuDigiLocker
from apps.api.core.settings import get_settings

#: The machine reasons a client's screen switches on. Client-facing sentences live in
#: `kyc_verification.py`, so one condition is never explained three ways.
NO_PROVIDER_CONFIGURED: Final = "no_provider_configured"
NO_WEBHOOK_SECRET: Final = "no_webhook_secret"
NO_API_CREDENTIALS: Final = "no_api_credentials"
PROVIDER_CONTRACT_UNVERIFIED: Final = "provider_contract_unverified"
#: The in-house adapter, named on a deployment that is not a developer's machine.
PROVIDER_NOT_LICENSED: Final = "provider_not_licensed"


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    """A provider, or the named reason there is none. Never both, never neither."""

    provider: IdentityVerificationProvider | None
    reason: str | None

    @property
    def available(self) -> bool:
        return self.provider is not None


def _build(name: str) -> IdentityVerificationProvider | str:
    """The adapter, or the reason its credentials are missing."""
    settings = get_settings()
    if name == "fake":
        secret = settings.kyc_verification_webhook_secret
        return FakeIdentityProvider(secret=secret) if secret else NO_WEBHOOK_SECRET
    if name == "cashfree":
        client_id = settings.kyc_verification_client_id
        client_secret = settings.kyc_verification_client_secret
        if not client_id or not client_secret:
            return NO_API_CREDENTIALS
        return CashfreeDigiLocker(
            client_id=client_id,
            client_secret=client_secret,
            environment=settings.kyc_verification_environment,
        )
    if name == "setu":
        return SetuDigiLocker()
    # Digio and Sandbox are members of the vocabulary — a stored reference has to be able
    # to name them — and have no adapter: their public docs did not show a wire contract
    # (docs/evidence/digilocker-kyc-providers-2026-10-08.md).
    raise ProviderContractUnverifiedError(f"No adapter has been written for {name!r}.")


def available_provider() -> ProviderCapability:
    """The one selector. Fails CLOSED at every step, with the reason attached."""
    settings = get_settings()
    name = settings.kyc_verification_provider
    if not name or name not in KYC_PROVIDERS:
        return ProviderCapability(None, NO_PROVIDER_CONFIGURED)
    if name == "fake" and settings.app_env != "local":
        # `fake` signs with a secret WE hold, so selecting it outside a developer's machine
        # would let a deployment mark its own clients verified — the forged verification
        # the signature check exists to prevent, arriving through the config instead.
        return ProviderCapability(None, PROVIDER_NOT_LICENSED)
    try:
        built = _build(name)
    except ProviderContractUnverifiedError:
        return ProviderCapability(None, PROVIDER_CONTRACT_UNVERIFIED)
    if isinstance(built, str):
        return ProviderCapability(None, built)
    # Constructing an adapter cannot fail for an unread contract, so without this the
    # registry would hand back an object that raises on its first call.
    if not built.contract_verified:
        return ProviderCapability(None, PROVIDER_CONTRACT_UNVERIFIED)
    return ProviderCapability(built, None)


__all__ = [
    "NO_API_CREDENTIALS",
    "NO_PROVIDER_CONFIGURED",
    "NO_WEBHOOK_SECRET",
    "PROVIDER_CONTRACT_UNVERIFIED",
    "PROVIDER_NOT_LICENSED",
    "ProviderCapability",
    "available_provider",
]
