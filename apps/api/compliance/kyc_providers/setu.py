"""Setu DigiLocker — DECLARED, NOT IMPLEMENTED, because its wire contract is unreadable here.

**EVERY METHOD RAISES. THAT IS THE FINISHED STATE OF THIS FILE, NOT A STUB.** The same
shape D-474 made of `PROVISIONING_IMPLEMENTED = False`: refused work, not unfinished
work. `available_provider()` never selects a provider whose contract is unattested, so
nothing reaches these methods in a running deployment; they raise so that a future
`kyc_verification_provider = "setu"` set by hand fails loudly at the seam instead of
silently accepting forged webhooks.

WHY IT IS NOT WRITTEN
----------------------
Writing it needs five vendor facts, and not one of them can be verified from this
container. Measured 20 September 2026, every host answering HTTP 000 / EGRESS_BLOCKED
through the agent proxy:

    UNKNOWN — docs.setu.co is egress-blocked here
    UNKNOWN — setu.co is egress-blocked here
    UNKNOWN — www.digilocker.gov.in is egress-blocked here
    UNKNOWN — apisetu.gov.in is egress-blocked here
    UNKNOWN — docs.digio.in, docs.cashfree.com, docs.sandbox.co.in, www.cashfree.com
              are egress-blocked here

A web SEARCH returns result titles for `docs.setu.co/data/digilocker/quickstart` and
`.../api-reference` but no body, and search-result titles are not a wire contract. Hard
rule 11: a signature scheme recalled from training is the single most dangerous thing
that could be written into this file, because it produces an endpoint that LOOKS
authenticated and is not — and this endpoint's whole job is to mark a client verified.

THE FIVE FACTS, AND THE PROMPT THAT FETCHES THEM
-------------------------------------------------
Hand this to Comet (or any browser-capable agent) and paste the answers back with the
page URL and the date beside each one; this module can then be written in an hour.

    Read https://docs.setu.co/data/digilocker/quickstart and
    https://docs.setu.co/data/digilocker/api-reference and answer ONLY from those
    pages, quoting the page and section for each answer. Say "not stated on these
    pages" rather than inferring:
      1. The exact HTTP request that CREATES a DigiLocker consent request: method,
         full path, required headers (including the names of the API-key headers),
         and the JSON request body with every required field.
      2. The exact success response of that call: the JSON field that carries the
         request id Setu will later quote back, and the field carrying the URL the
         end user is redirected to.
      3. The webhook: the exact HTTP header name carrying the signature, the exact
         algorithm, what bytes are signed (raw body only? body plus a timestamp? a
         canonical string?), the encoding of the digest (hex or base64), and where
         the signing secret comes from.
      4. The webhook body for a COMPLETED verification: which field says success vs
         failure, which field carries the request id, and which field carries the
         verified holder's NAME.
      5. Whether the Aadhaar number itself appears anywhere in the webhook body or in
         any document-fetch response, and whether there is a documented option to
         receive a response with the number masked or omitted entirely.

Fact 5 is a gate, not a curiosity. If Setu's completed-verification payload carries the
number, this adapter must request the masked/omitted variant, and if no such variant
exists then Setu is REFUSED for this product and another provider is read instead —
because a payload we receive is a payload we hold, however briefly, and `/legal/privacy`
tells clients we do not.

WHAT IS ALREADY DECIDED AND NEEDS NO VENDOR FACT
-------------------------------------------------
The redirect-based flow, the four normalized facts, the request row the webhook resolves
a tenant from, the idempotency key, both entity branches and the widened evidence
constraint are all built and tested against `fake.py`. What is missing is one vendor's
spelling of a signature header and a JSON body — which is the correct thing to be missing,
and the cheapest thing to add.
"""

from __future__ import annotations

from apps.api.compliance.kyc_providers.base import (
    ProviderContractUnverifiedError,
    VerificationOutcome,
    VerificationStart,
)

_WHY = (
    "The Setu DigiLocker wire contract has not been read from Setu's own documentation: "
    "docs.setu.co and setu.co are egress-blocked from this deployment's build "
    "environment (measured 20 Sep 2026). The five facts required, and the prompt that "
    "fetches them, are in this module's docstring."
)


class SetuDigiLocker:
    """Placeholder for the real adapter. Selecting it is a configuration error."""

    @property
    def name(self) -> str:
        return "setu"

    @property
    def contract_verified(self) -> bool:
        return False

    async def start(self, *, entity_type: str, redirect_back_url: str) -> VerificationStart:
        raise ProviderContractUnverifiedError(_WHY)

    def verify_webhook(self, *, raw: bytes, headers: dict[str, str]) -> bool:
        # NOT `return False`. False would read as "this delivery was not signed correctly"
        # and let a caller treat the endpoint as working-and-strict; it is neither.
        raise ProviderContractUnverifiedError(_WHY)

    def parse_outcome(self, *, raw: bytes) -> VerificationOutcome:
        raise ProviderContractUnverifiedError(_WHY)


__all__ = ["SetuDigiLocker"]
