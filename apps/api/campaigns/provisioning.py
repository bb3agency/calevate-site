"""Number provisioning — a capability this product does not offer, and the refusals for it.

**MODEL B: CALEVATE DOES NOT SUPPLY, SELL, RENT, ALLOCATE OR PROVISION A PHONE NUMBER.**
The client takes the telephone connection on their OWN Exotel / Plivo / Vobiz account,
passes that carrier's KYC, remains the subscriber of record, and issues us API
credentials they can withdraw. That is `docs/legal/LEGAL-OPS-PLAYBOOK.md:24` and §9
(`:239-317`); Model A — Calevate holding numbers and allocating them — is refused
outright for a sole proprietor with no corporate veil (`:249`), a client asking "just
give me a number" is sent to the carrier or lost as a deal (`:266`), and the stop-list
forbids both reselling from a pool and parking client traffic on a Calevate carrier
account (`:600-614`, items 1 and 10). The published Terms (clause 3) and Acceptable Use
§2.1 tell the client the same thing in the same words.

So this module provisions nothing, and the reason is a DECISION and not a missing
credential. It used to read as an unfinished integration waiting for an `EXOTEL_*`
secret; it is not, and every string it hands a human now says which it is. What is left
is worth having on its own: the KYC gate below, which is real and is required whichever
carrier the client buys from, and one place that answers "can you get me a number?" with
the true answer and the next step, rather than with silence or a support ticket.

**No vendor SDK is added, no request or response shape is invented, and no provisioning
API is described here.** Guessing a vendor contract and finding out in production is
exactly what D-31/D-32 exist to prevent, and hard rule 9 makes adding a package on a
guess a supply-chain decision rather than a convenience.

WHAT IS ACTUALLY DECIDED, AND WHAT IS ONLY CONFIGURED
-----------------------------------------------------
- `NUMBER_PROVIDER` names the carrier this deployment would deal with IF Model A were
  ever adopted. It is config rather than an inference from "is there a key", for the
  reason `payment_capability` spells out: a credential is not a statement that a
  capability exists, and two independent reads of the same settings eventually disagree.
  Setting it changes nothing today — the constant below is what decides.
- `number_provisioning_capability()` is the ONE selector. The purchase route asks it and
  the client's own KYC screen asks it, so the screen cannot offer a button the route
  refuses. There is no second read of settings anywhere.
- `PROVISIONING_IMPLEMENTED = False` is the greppable constant for a capability that is
  not offered — the shape of `ingest.meta.LEAD_RETRIEVAL_IMPLEMENTED` and
  `payments.PROVIDER_CREATES_ORDERS`, but with a different KIND of reason behind it: no
  adapter exists because none is wanted. It is a constant and not a comment so the claim
  is testable, and `tests/kyc_gate_test.py` fails the moment it is flipped without an
  adapter behind it. **Flipping it is adopting Model A**, which is a legal decision
  (incorporate first, obtain written VNO/reseller status — playbook `:621`) and needs a
  decision-log entry, not a config change.

WHY KYC IS ASKED FIRST, AND FOR EVERY TIER
-------------------------------------------
The KYC check runs BEFORE the capability check even though the capability check refuses
every request. The KYC refusal is the one the client can act on, and it is the one that
is true of them under Model B as well: their own carrier blocks outgoing calls until
their KYC clears (Exotel, cited below), and our dial gate reads the same record. So a
client who has filed nothing learns the thing that is blocking them everywhere, and a
client who is verified learns the thing that is only true of us — that we do not sell
numbers, and where to buy one. Reversing the order would put our business model in front
of their blocker and leave the compliance control unexercised.

And it is asked with **no plan-tier test at all**, unlike the dial-time gate. The DoT
business-connection obligation attaches to the connection and has no managed-client
exemption; keying it on `plan_tier` — an admin-settable column — would put a legal
control one support ticket away from being switched off, which is the "bypass for
testing" hard rule 5 forbids. `apps/api/compliance/kyc.py` argues the whole
managed/self-serve split, including why the DIAL gate answers the question differently.

Nothing here writes. A refusal allocates no number, records no intent and touches no
row — there is no half-provisioned state to reconcile, because there is no state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.kyc import KYC_MISSING_REASON, kyc_not_verified_reason, read_kyc
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings

log = get_logger(__name__)

# D-05's telephony picks — the carriers a CLIENT buys their own connection from, which is
# the only relationship Model B has with any of them. A name outside this tuple resolves to
# `provider_not_implemented` rather than looking configured — `NUMBER_PROVIDER=twilio`
# must fail loudly, not quietly behave like Exotel.
#
# **`plivo` WAS MISSING AND IT IS THE CARRIER FOR HALF OUR REGULATED NUMBERS.** The
# engine's own regulated-numbers guide maps the two series our `NUMBER_SERIES` enum
# names onto two carriers, and it is a table, not a hedge (`bolna-findings/mirror/pages/
# guides/inbound/obtaining-regulated-phone-numbers.md:15-16`):
#
#     | **140-series** | Telemarketing and promotional calls | Vobiz  |
#     | **160-series** | Transactional and service calls ... | Plivo  |
#
# So an operator who set `NUMBER_PROVIDER=plivo` — naming the vendor that actually
# allocates the 160-series numbers every agent we publish runs on, and the one
# `engine/bolna.py` hardcodes into `tools_config.input/output.provider` — was told
# `provider_not_implemented:plivo`, i.e. "we do not support that vendor". That is the
# WRONG refusal: the vendor is supported and the ADAPTER is what is missing, which is
# the distinction the two reason codes below exist to keep apart. Now it resolves to
# `no_provisioning_adapter:plivo` like its siblings.
#
# `exotel` stays, and is deliberately not the same kind of entry. Bolna's number-purchase
# API cannot broker an Exotel number at all — `POST /phone-numbers/buy`'s provider enum is
# `twilio | plivo | vobiz` (`bolna-findings/mirror/pages/api-reference/phone-numbers/
# buy.md:67-73`) — but Exotel is a first-class BYO-ACCOUNT integration there
# ("Bring Your Own Account | ✅ Yes", `.../supported-telephony-providers.md:32`), so an
# Exotel number is bought FROM EXOTEL by the client and connected. This constant answers
# "which carrier a client may hold their own connection with", not "which vendor Bolna
# will buy one from" and not "which vendor sells Calevate a number" — nobody does.
# `twilio` is still absent on purpose: it is the non-India provider
# (`.../supported-telephony-providers.md:34` lists its countries and India is not one).
KNOWN_PROVIDERS: Final[tuple[str, ...]] = ("exotel", "plivo", "vobiz")

# Is there an adapter that can ask a provider for a number? NO, and there is not meant to
# be one: buying a number for a client is Model A. See the module docstring. Greppable and
# testable rather than a note in a doc.
PROVISIONING_IMPLEMENTED: Final = False

# Authored reason codes — never vendor prose. They name OUR configuration state, are
# logged, and are never returned to a client (telling them which of our secrets is
# missing is an internals leak).
NO_PROVIDER_REASON: Final = "no_number_provider"
PROVIDER_NOT_IMPLEMENTED_REASON: Final = "provider_not_implemented"
NO_ADAPTER_REASON: Final = "no_provisioning_adapter"


@dataclass(frozen=True, slots=True)
class NumberProvisioningCapability:
    """What this deployment can do about buying a number, as ONE answer.

    `reason` is non-None exactly when `available` is False. `provisions_numbers` is
    carried on the same object rather than read separately so a caller cannot conclude
    "a provider is configured" and then assume "so a number can be bought" — those are
    different facts and conflating them is how a UI grows a button nothing serves.
    """

    available: bool
    provider: str | None = None
    reason: str | None = None
    provisions_numbers: bool = False


def number_provisioning_capability() -> NumberProvisioningCapability:
    """THE selector. Every surface that cares asks this; nothing re-reads settings."""
    provider = (get_settings().number_provider or "").strip().lower()
    if not provider:
        return NumberProvisioningCapability(available=False, reason=NO_PROVIDER_REASON)
    if provider not in KNOWN_PROVIDERS:
        return NumberProvisioningCapability(
            available=False,
            provider=provider,
            reason=f"{PROVIDER_NOT_IMPLEMENTED_REASON}:{provider}",
        )
    # A recognised vendor with nothing behind it. Reported as its own reason rather than
    # folded into the one above, because "you named a vendor we do not support" and "you
    # named the right vendor and we never wrote the client" are different operator
    # problems with different fixes.
    return NumberProvisioningCapability(
        available=PROVISIONING_IMPLEMENTED,
        provider=provider,
        reason=None if PROVISIONING_IMPLEMENTED else f"{NO_ADAPTER_REASON}:{provider}",
        provisions_numbers=PROVISIONING_IMPLEMENTED,
    )


def number_purchase_available() -> bool:
    """The boolean a screen wants — the SAME selector the route uses, so a screen that
    offers the button and a route that refuses it cannot disagree."""
    return number_provisioning_capability().available


def provisioning_not_configured(reason: str | None) -> ProblemError:
    """The ONE deployment-side refusal, so every surface says it the same way.

    RFC-9457: the machine code is the LAST SEGMENT of `type`, and there is no `code`
    key. The authored `reason` is logged for an operator and never returned — a client
    cannot act on `no_provisioning_adapter`.
    """
    log.warning("number_provisioning_unavailable", extra={"reason": reason or "unknown"})
    return ProblemError(
        kind="dependency",
        code="number_provisioning_not_configured",
        title="We do not supply phone numbers",
        detail=(
            "Calevate does not sell, rent or provision telephone numbers. Your calling "
            "number is a connection you take in your own name, on your own account with "
            "an Indian operator, and you stay the subscriber of record for it."
        ),
        remediation=(
            "Open an account with an Indian operator — Exotel, Plivo or Vobiz — pass "
            "their KYC and take the number there, then send us the account credentials "
            "and the number and we will connect it to your agents. You can withdraw "
            "those credentials at any time."
        ),
    )


async def assert_kyc_verified_for_provisioning(session: AsyncSession, *, tenant_id: UUID) -> None:
    """The client-side gate. Tier-blind (module docstring). Raises; writes nothing.

    One machine code for both failures — `kyc_not_verified` — because the client's next
    action is the same either way (send us the documents); the DETAIL distinguishes
    "nothing on file" from "filed and not cleared", which is what
    `GET /v1/compliance/kyc` then shows them in full. The dial-time gate splits them
    into two rule names instead, because a launch screen lists blockers by rule and an
    operator reading that list wants the two states apart.
    """
    record = await read_kyc(session, tenant_id=tenant_id)
    if record.is_verified:
        return
    detail = (
        KYC_MISSING_REASON if not record.recorded else kyc_not_verified_reason(str(record.status))
    )
    raise ProblemError.business_rule(
        "kyc_not_verified",
        detail,
        remediation=(
            "Send us your business registration details so we can verify the account. "
            "Your operator will ask for the same documents when you take the connection "
            "in your own name."
        ),
    )


__all__ = [
    "KNOWN_PROVIDERS",
    "NO_ADAPTER_REASON",
    "NO_PROVIDER_REASON",
    "PROVIDER_NOT_IMPLEMENTED_REASON",
    "PROVISIONING_IMPLEMENTED",
    "NumberProvisioningCapability",
    "assert_kyc_verified_for_provisioning",
    "number_provisioning_capability",
    "number_purchase_available",
    "provisioning_not_configured",
]
