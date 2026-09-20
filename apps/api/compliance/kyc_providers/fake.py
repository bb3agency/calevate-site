"""The in-house provider — a REAL adapter over a contract we own, not a mock.

Same role `engine/fake.py` plays for the voice engine, and it exists for a sharper reason
here: no vendor's DigiLocker contract is readable from this environment (see `setu.py`),
so without this adapter the entire client-verification seam — the request row, the tenant
resolution, the signature refusal, the replay, both entity branches, the widened evidence
constraint — would be code nothing has ever executed. The behaviour that matters is
proven against this, and swapping in a vendor changes one file.

ITS SIGNATURE SCHEME IS OURS AND THEREFORE VERIFIABLE
------------------------------------------------------
HMAC-SHA256 over the RAW REQUEST BYTES, hex, compared with `hmac.compare_digest`, in the
header `x-calevate-kyc-signature`. Every element is a choice this repo makes and can
state, which is the whole point: `billing/payments.verify_signature` implements the same
three properties against Razorpay's scheme, and the reasons carry over unchanged —

* the raw bytes, never a re-serialized dict, because a signature covers what was SENT and
  a round-tripped body compares against something the sender never signed;
* `compare_digest`, so a wrong signature leaks no timing information about how much of it
  was right;
* a missing header is a refusal rather than a skip, because "unsigned" must not be a way
  to opt out of being checked.

It is NOT a claim about any vendor's scheme. A vendor adapter implements the vendor's,
read from the vendor's own page.

WHEN THIS MAY BE SELECTED
--------------------------
Only when `kyc_verification_provider` names it, which no production deployment does — the
field defaults to unset and `available_provider()` then answers unavailable with a reason
a client's screen can render. It is for the test suite and for a developer driving the
flow locally without a vendor account.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from uuid import uuid4

from apps.api.compliance.kyc_providers.base import VerificationOutcome, VerificationStart

#: The header this adapter signs into. Ours, so it is spelled once and here.
SIGNATURE_HEADER = "x-calevate-kyc-signature"

#: Our own field names — the four facts of `VerificationOutcome`, nothing more. A vendor
#: adapter maps ITS names onto these; this one has no mapping to do.
_REF = "provider_ref"
_VERIFIED = "verified"
_NAME = "verified_name"
_REASON = "failure_reason"


def sign(*, secret: str, body: bytes) -> str:
    """The digest a caller must present. Exported so tests sign the way the route verifies
    rather than restating the scheme — two spellings of one scheme is how they drift."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class FakeIdentityProvider:
    """A provider that accepts a run and reports whatever the webhook body says."""

    def __init__(self, *, secret: str) -> None:
        self._secret = secret

    @property
    def name(self) -> str:
        return "fake"

    @property
    def contract_verified(self) -> bool:
        # The contract is OURS — defined in this module's docstring and implemented
        # below — so there is no vendor page to read and nothing to be wrong about.
        return True

    async def start(self, *, entity_type: str, redirect_back_url: str) -> VerificationStart:
        ref = f"fake-{uuid4()}"
        # A real provider hosts this page; ours points back at the caller's own return
        # URL so a local run completes without a second service. The query parameter
        # carries the run id because that is what a provider's redirect does.
        return VerificationStart(
            provider_ref=ref, redirect_url=f"{redirect_back_url}?provider_ref={ref}"
        )

    def verify_webhook(self, *, raw: bytes, headers: dict[str, str]) -> bool:
        presented = headers.get(SIGNATURE_HEADER)
        if not presented:
            return False
        return hmac.compare_digest(presented.strip(), sign(secret=self._secret, body=raw))

    def parse_outcome(self, *, raw: bytes) -> VerificationOutcome:
        body: Any = json.loads(raw or b"{}")
        if not isinstance(body, dict):
            body = {}
        verified = body.get(_VERIFIED) is True
        name = body.get(_NAME)
        reason = body.get(_REASON)
        return VerificationOutcome(
            provider_ref=str(body.get(_REF) or ""),
            verified=verified,
            verified_name=str(name)
            if verified and isinstance(name, str) and name.strip()
            else None,
            # A failure with no reason is the ticket nobody can close, and the DB CHECK
            # refuses one — so a default is supplied here rather than letting the write
            # fail on a payload we cannot improve.
            failure_reason=None
            if verified
            else (str(reason) if isinstance(reason, str) and reason.strip() else "not_completed"),
        )


__all__ = ["SIGNATURE_HEADER", "FakeIdentityProvider", "sign"]
