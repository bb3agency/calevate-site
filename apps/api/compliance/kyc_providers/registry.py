"""Which provider this deployment may use, and the named reason when none may.

THE ANSWER TODAY IS NONE, AND THAT IS THE GATE WORKING RATHER THAN A GAP. Two conditions
have to hold, and they are separate facts about separate things:

1. **A provider is configured** — `Settings.kyc_verification_provider` names a member of
   `KYC_PROVIDERS`. Unset is the state of every deployment.
2. **Its webhook secret is installed** — `Settings.kyc_verification_webhook_secret`, from
   the provider's own console, in the ops console's encrypted path. Without it the
   receiver cannot verify a signature, and a receiver that cannot verify a signature must
   not exist: this endpoint's entire job is to mark a client VERIFIED, so an unverifiable
   feed grants identity on anyone's say-so. That is strictly worse than no feed, which is
   the same argument `payment_capability` makes about crediting a wallet, one notch
   sharper because a forged payment costs money and a forged verification costs a
   defence.

**ONE SELECTOR, ASKED BY EVERYONE.** The start route, the client's own screen and the
webhook all call this, so a screen can never offer a button the route refuses and the
webhook can never accept a delivery for a provider the product is not on. Same discipline
`number_purchase_available` and `payment_capability` follow; the failure it prevents is
the one where three surfaces each decide "configured enough" differently.

**WHAT DOES NOT GATE IT**: nothing about `kyc_records`, and nothing about the tier. A
deployment's ability to run a verification is a property of the deployment; whether a
given tenant NEEDS one is `compliance.service`'s question and is deliberately not asked
here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from apps.api.compliance.kyc_providers.base import (
    KYC_PROVIDERS,
    IdentityVerificationProvider,
    ProviderContractUnverifiedError,
)
from apps.api.compliance.kyc_providers.fake import FakeIdentityProvider
from apps.api.compliance.kyc_providers.setu import SetuDigiLocker
from apps.api.core.settings import get_settings

#: The machine reasons a client's screen switches on. Client-facing sentences live in
#: `kyc.py` beside the other two refusals, so one condition is never explained three ways.
NO_PROVIDER_CONFIGURED: Final = "no_provider_configured"
NO_WEBHOOK_SECRET: Final = "no_webhook_secret"
PROVIDER_CONTRACT_UNVERIFIED: Final = "provider_contract_unverified"


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    """A provider, or the named reason there is none. Never both, never neither."""

    provider: IdentityVerificationProvider | None
    reason: str | None

    @property
    def available(self) -> bool:
        return self.provider is not None


def _build(name: str, *, secret: str) -> IdentityVerificationProvider:
    if name == "fake":
        return FakeIdentityProvider(secret=secret)
    if name == "setu":
        return SetuDigiLocker()
    # Digio, Cashfree and Sandbox are members of the vocabulary — a stored reference has
    # to be able to name them — and have no adapter for the same reason Setu's is
    # declared-and-unimplemented: their docs are egress-blocked from here and a wire
    # contract recalled from memory is the one thing hard rule 11 forbids outright.
    raise ProviderContractUnverifiedError(
        f"No adapter has been written for {name!r}: its wire contract has not been read "
        "from the vendor's own documentation. See `kyc_providers/setu.py` for the five "
        "facts required and the prompt that fetches them."
    )


def available_provider() -> ProviderCapability:
    """The one selector. Fails CLOSED at every step, with the reason attached."""
    settings = get_settings()
    name = settings.kyc_verification_provider
    if not name or name not in KYC_PROVIDERS:
        return ProviderCapability(None, NO_PROVIDER_CONFIGURED)
    secret = settings.kyc_verification_webhook_secret
    if not secret:
        return ProviderCapability(None, NO_WEBHOOK_SECRET)
    try:
        provider = _build(name, secret=secret)
    except ProviderContractUnverifiedError:
        # A configured provider with no adapter at all. Answered as unavailable rather
        # than raised: the client's screen asks this selector too, and a 500 there tells
        # a blocked client nothing they can act on. The operator's signal is the reason.
        return ProviderCapability(None, PROVIDER_CONTRACT_UNVERIFIED)
    # THE SECOND HALF, AND IT IS NOT REDUNDANT. Constructing an adapter cannot fail for
    # an unread contract — a class with unwritten methods instantiates perfectly well —
    # so without this the registry hands back an object that raises on its first call,
    # which is a 500 on the webhook instead of a refusal at the gate.
    if not provider.contract_verified:
        return ProviderCapability(None, PROVIDER_CONTRACT_UNVERIFIED)
    return ProviderCapability(provider, None)


__all__ = [
    "NO_PROVIDER_CONFIGURED",
    "NO_WEBHOOK_SECRET",
    "PROVIDER_CONTRACT_UNVERIFIED",
    "ProviderCapability",
    "available_provider",
]
