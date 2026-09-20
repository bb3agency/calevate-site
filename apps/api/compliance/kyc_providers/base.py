"""What a client identity-verification provider must do, in OUR vocabulary.

D-635. A client verifies themselves by authenticating DIRECTLY with a licensed
aggregator's DigiLocker flow. We never see the Aadhaar, the PAN or the document; four
facts come back and those four are the whole of our interest:

    verified or not · which provider · that provider's reference · the holder's NAME

Everything below is expressed in those terms. A provider adapter's job is to translate a
vendor's shapes into them and to keep the vendor's shapes on its own side of this file —
the same boundary `ingest/meta.py` holds for Meta and `billing/payments.py` for Razorpay.
(Hard rule 2 is about the VOICE ENGINE's vendors and `apps.api.engine.*` is what
import-linter forbids by name; a KYC aggregator is a vendor of the second kind, and this
module is where its shapes stop.)

WHY A PROTOCOL AND NOT ONE VENDOR'S CLIENT
-------------------------------------------
Four providers are plausible — Setu, Digio, Cashfree, Sandbox — and which one this
product ends up on is a commercial question nobody here can settle. The cost of the
Protocol is one file; the cost of not having it is that the vendor's field names reach
the route, the record and eventually a column, and the second provider is a rewrite. The
same argument `calevate_shared.retrieval.RetrievalProvider` makes for the vector store.

THE TWO ENTITY BRANCHES, AND WHY THE PROVIDER DOES NOT DECIDE THEM
-------------------------------------------------------------------
A DigiLocker run identifies a NATURAL PERSON. What that person IS to the business is our
question, not the provider's:

* **`sole_proprietorship`** — the proprietor IS the entity in law. Verifying the person
  verifies the subscriber, so an aggregator result completes the record on its own.
* **every other entity type** — the person is the AUTHORISED SIGNATORY. A verified
  signatory is necessary and not sufficient: the entity still needs its CIN/LLPIN/GSTIN
  recorded against a public register, which is `document_kind`/`document_ref` and remains
  an operator's job (D-47's path, which this decision does not retire). So an aggregator
  result on a company moves the record to `submitted` with the signatory verified, never
  straight to `verified`.

`entity_branch()` is the one place that distinction is made, so the route, the webhook and
the record cannot answer it three different ways.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from apps.api.compliance.models import KYC_PROVIDERS

#: Re-exported, NOT redefined. The vocabulary lives with the other KYC vocabularies in
#: `compliance/models.py`, beside the CHECK constraint that enforces it; a second tuple
#: here would be a second source of truth for one set, and the copy that drifted would be
#: the one the config field validates against.

#: Which branch an entity type takes. `sole_proprietorship` is the only one where the
#: verified person and the subscribing entity are the same legal person.
EntityBranch = Literal["proprietor_is_the_entity", "signatory_of_an_entity"]

_PROPRIETORSHIP = "sole_proprietorship"


def entity_branch(entity_type: str) -> EntityBranch:
    """Which of the two shapes this verification is, decided once.

    A company's authorised signatory being verified does NOT verify the company — the
    registry document still has to be checked against a public register, and only an
    operator does that. Getting this wrong in one caller would mark a company verified on
    a personal Aadhaar authentication, which is the exact outcome D-635 is shaped to
    avoid.
    """
    return (
        "proprietor_is_the_entity" if entity_type == _PROPRIETORSHIP else "signatory_of_an_entity"
    )


@dataclass(frozen=True, slots=True)
class VerificationStart:
    """A run the provider has accepted and the client has not yet completed.

    `redirect_url` is where the client's browser goes to authenticate — at the PROVIDER,
    never here, which is the property that keeps the Aadhaar out of this system.
    `provider_ref` is the provider's id for the run and is what the webhook is later
    resolved by; we store it before redirecting, so an outcome we did not initiate has no
    row to land on.
    """

    provider_ref: str
    redirect_url: str


@dataclass(frozen=True, slots=True)
class VerificationOutcome:
    """The result, normalized. FOUR fields, and no fifth is ever added here.

    `verified_name` is the holder name as the source record spells it — a NAME, and
    deliberately not the number it was read from. `failure_reason` is our word for why,
    never the vendor's raw payload, because it is rendered to a client.
    """

    provider_ref: str
    verified: bool
    verified_name: str | None = None
    failure_reason: str | None = None


class ProviderContractUnverifiedError(RuntimeError):
    """This adapter's wire contract has not been read from the vendor's own docs.

    Raised rather than guessed. Hard rule 11: a signature scheme recalled or inferred is
    worse than none, because it produces an endpoint that LOOKS authenticated and accepts
    whatever an attacker sends. `available_provider()` is what keeps this from being
    reachable at runtime; this exception is the backstop if somebody selects one anyway.
    """


@runtime_checkable
class IdentityVerificationProvider(Protocol):
    """One licensed aggregator, behind our four facts.

    `verify_webhook` takes the RAW BYTES, never a parsed body: a signature covers what was
    sent, and re-serializing a dict to check it compares against something the sender
    never signed (the argument `billing/payments.verify_signature` makes at length). It
    returns a bool and raises nothing for a bad signature — the route decides what a
    refusal looks like.
    """

    @property
    def name(self) -> str:
        """The member of `KYC_PROVIDERS` this adapter is."""

    @property
    def contract_verified(self) -> bool:
        """Has this adapter's wire contract been read from the vendor's own docs?

        A PROPERTY OF THE ADAPTER, not of the registry, and it is False by construction
        for every provider whose documentation nobody here has been able to open. It has
        to live here because CONSTRUCTING an adapter cannot fail for this reason — a
        class with unwritten methods instantiates perfectly well — so a registry that
        only caught construction errors would hand out an object that 500s on its first
        call. `tests/kyc_provider_seam_test.py` found exactly that.
        """

    async def start(self, *, entity_type: str, redirect_back_url: str) -> VerificationStart:
        """Open a run at the provider and hand back where to send the client."""

    def verify_webhook(self, *, raw: bytes, headers: dict[str, str]) -> bool:
        """True only if these exact bytes carry this provider's valid signature."""

    def parse_outcome(self, *, raw: bytes) -> VerificationOutcome:
        """Translate a VERIFIED delivery into our four facts. Never called before
        `verify_webhook` has returned True."""


__all__ = [
    "KYC_PROVIDERS",
    "EntityBranch",
    "IdentityVerificationProvider",
    "ProviderContractUnverifiedError",
    "VerificationOutcome",
    "VerificationStart",
    "entity_branch",
]
