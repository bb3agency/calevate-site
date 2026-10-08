"""Setu DigiLocker — DECLARED, NOT IMPLEMENTED, because Cashfree was chosen (D-692).

Setu's DigiLocker reference is public and was read on 8 Oct 2026
(https://docs.setu.co/data/digilocker/quickstart): `POST /api/digilocker/` on
`dg-sandbox.setu.co` / `dg.setu.co` with `x-client-id`, `x-client-secret` and
`x-product-instance-id`, a `redirectUrl` body, a polled `GET /api/digilocker/:id/status`,
and `GET /api/digilocker/:id/aadhaar`, whose response carries the holder's address, date of
birth, photo and a link to the Aadhaar XML. No webhook is documented. The comparison that
chose Cashfree instead — mainly that Setu's Aadhaar fetch hands us far more personal data
than the name we keep — is `docs/evidence/digilocker-kyc-providers-2026-10-08.md`.

Every method raises so that `kyc_verification_provider = "setu"` set by hand fails at the
seam instead of half-working; `available_provider()` answers `provider_contract_unverified`
for it. Writing it is a one-file change against the page above if the choice is reversed.
"""

from __future__ import annotations

from apps.api.compliance.kyc_providers.base import (
    IdDocument,
    ProviderContractUnverifiedError,
    VerificationOutcome,
    VerificationStart,
)

_WHY = (
    "The Setu DigiLocker adapter is not implemented: Cashfree is the chosen provider "
    "(D-692). See docs/evidence/digilocker-kyc-providers-2026-10-08.md."
)


class SetuDigiLocker:
    """Placeholder. Selecting it is a configuration error."""

    @property
    def name(self) -> str:
        return "setu"

    @property
    def contract_verified(self) -> bool:
        return False

    @property
    def webhook_is_authoritative(self) -> bool:
        return False

    async def start(
        self, *, entity_type: str, redirect_back_url: str, id_document: IdDocument
    ) -> VerificationStart:
        raise ProviderContractUnverifiedError(_WHY)

    async def fetch_outcome(
        self, *, provider_ref: str, id_document: IdDocument
    ) -> VerificationOutcome | None:
        raise ProviderContractUnverifiedError(_WHY)

    def verify_webhook(self, *, raw: bytes, headers: dict[str, str]) -> bool:
        # NOT `return False`, which would read as "a badly signed delivery" and let a
        # caller treat the endpoint as working-and-strict; it is neither.
        raise ProviderContractUnverifiedError(_WHY)

    def parse_outcome(self, *, raw: bytes) -> VerificationOutcome:
        raise ProviderContractUnverifiedError(_WHY)


__all__ = ["SetuDigiLocker"]
