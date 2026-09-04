"""Number provisioning — what this deployment may buy, and the two gates in front of it.

**MODEL A IS ADOPTED ON THE INBOUND LEG, BY THE FOUNDER, ON 4 SEP 2026 (D-535), AND THIS
MODULE USED TO SAY THE OPPOSITE IN ITS FIRST LINE.** Calevate buys an Indian DID through
the voice engine; the clinic keeps its own published number and conditionally forwards it
to ours. The client-facing story is "point your existing phone at this number", the DID is
never published, and forwarding is configured on the client's own line by their own
carrier — no code, no credential, nothing of ours.

**MODEL B IS NOT WITHDRAWN AND IS STILL THE OTHER HALF OF THE PRODUCT.** A client who
holds their own Exotel / Plivo / Vobiz connection still brings it, still passes that
carrier's KYC, still stays the subscriber of record and still issues us revocable
credentials; `agents.service.provision_number` RECORDS that number and asks no operator
for anything (`docs/legal/LEGAL-OPS-PLAYBOOK.md` §9, `:239-317`). The two models now
coexist, and the difference between them is one column — `phone_numbers.engine_owned` —
not two code paths.

THE TWO GATES, AND WHY THEY ARE DIFFERENT KINDS OF FACT
-------------------------------------------------------
1. **CAN the engine sell us one?** `EngineCapabilities.number_series`. Bolna answers
   "standard, and no DLT class" (`engine/bolna.py`); Cartesia answers "none". This is a
   VENDOR capability, read from the descriptor, never from a settings key.
2. **MAY WE?** `Settings.number_resale_authorization`. The playbook's condition on this
   decision is not waived, it is SEQUENCED: *"A future 'we provision the number for
   self-serve' tier is Model A and is unsafe for a proprietor. If you ever do it:
   incorporate first, get written VNO/reseller status from a licensed operator"*
   (`:621`), and the stop-list forbids reselling from a pool in our name and parking
   client traffic on a Calevate carrier account (`:600-614`, items 1 and 10). The founder
   has neither today. So the code is built and the GOING LIVE is gated on a written
   status an operator records — deliberately, in the ops console, naming the instrument.
   OPERATIONS §2 gate 45.

   **"THE CODE IS READY" AND "IT IS LAWFUL FOR US TO RESELL NUMBERS" ARE DIFFERENT FACTS
   AND THIS MODULE EXISTS SO THE PRODUCT CANNOT CONFLATE THEM.** That is also why the gate
   is a REFERENCE and not a boolean: a checkbox records that somebody clicked, and what is
   needed is which document was relied on.

⚠ **THE INDIAN REGULATORY POSITION IS AN UNKNOWN, NOT A FINDING, AND NOTHING HERE MAY BE
READ AS CLEARING IT.** The primary sources were not reachable this session: DoT's own
revised OSP guidelines PDF and `www.dot.gov.in` are EGRESS-BLOCKED from this container
(measured 4 Sep 2026, 403 on CONNECT), so the only things available were consultants'
summaries — REPORTED, not primary, and not usable for a compliance conclusion under hard
rule 11. What is therefore NOT established here: whether a DID bought through a licensed
operator's reseller and assigned to a client is an assignment requiring a UL(VNO)
authorisation; whether the 2020 repeal of OSP registration leaves any obligation that
attaches to us; and what "shall not provide switched telephony" reaches. Gate 45 puts all
three to the advocate, in those words. None of them is answered by this file.

WHAT SELF-SERVE STILL IS: REFUSED
----------------------------------
`POST /v1/numbers/purchase` — the client-realm route — still refuses every request, and
that is unchanged by the decision. Playbook §19 names "we provision the number for
self-serve" as the unsafe shape specifically; what the founder adopted is an
OPERATOR-LED supply, arranged as part of onboarding. So the refusal survives and only its
COPY changed: it used to say we do not supply numbers at all, which is no longer true.

WHY KYC IS ASKED FIRST, AND FOR EVERY TIER
-------------------------------------------
Unchanged, and it matters more under Model A rather than less. The KYC check runs BEFORE
the capability check. Under Model B the refusal a client can act on is their own carrier's;
under Model A the connection is taken in OUR name and the DoT business-connection
obligation attaches to the subscriber of record — which is now us — so knowing who we are
putting on it is not paperwork, it is the point. It is asked with **no plan-tier test at
all**, unlike the dial-time gate: keying a legal control on `plan_tier`, an admin-settable
column, would put it one support ticket away from being switched off, which is the "bypass
for testing" hard rule 5 forbids. `apps/api/compliance/kyc.py` argues the whole
managed/self-serve split.

Nothing here writes. A refusal allocates no number, records no intent and touches no row.
The module that actually spends money is `campaigns/number_supply.py`, and it takes both
gates from here rather than re-reading either.
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
from apps.api.engine.capabilities import engine_capabilities

log = get_logger(__name__)

# The carriers a CLIENT may hold their OWN connection with — Model B's whole relationship
# with any of them, and untouched by D-535. A name outside this tuple resolves to
# `provider_not_implemented` rather than looking configured: `NUMBER_PROVIDER=twilio` must
# fail loudly, not quietly behave like Exotel.
#
# `plivo` and `vobiz` are here because the engine's own regulated-numbers guide maps the
# two series our `NUMBER_SERIES` enum names onto them, and it is a table, not a hedge
# (`bolna-findings/mirror/pages/guides/inbound/obtaining-regulated-phone-numbers.md:15-16`):
#
#     | **140-series** | Telemarketing and promotional calls | Vobiz  |
#     | **160-series** | Transactional and service calls ... | Plivo  |
#
# `exotel` stays and is deliberately not the same kind of entry. Bolna's number-purchase
# API cannot broker an Exotel number at all — `POST /phone-numbers/buy`'s provider enum is
# `twilio | plivo | vobiz` (`bolna-findings/mirror/pages/api-reference/phone-numbers/
# buy.md:67-73`) — but Exotel is a first-class BYO-ACCOUNT integration there
# ("Bring Your Own Account | ✅ Yes", `.../supported-telephony-providers.md:32`), so an
# Exotel number is bought FROM EXOTEL by the client and connected.
# `twilio` is absent on purpose: it is the non-India provider
# (`.../supported-telephony-providers.md:34` lists its countries and India is not one).
#
# ⚠ **THIS IS NOT THE LIST OF PROVIDERS WE MAY BUY FROM.** That set is the engine's
# (`buy.md:67-73`) and is asked of the engine, per purchase, from the search result an
# operator picked. Two questions, two answers; conflating them is how `NUMBER_PROVIDER`
# would come to decide something it knows nothing about.
KNOWN_PROVIDERS: Final[tuple[str, ...]] = ("exotel", "plivo", "vobiz")

# Authored reason codes — never vendor prose. They name OUR configuration or legal state,
# are logged, and are never returned to a client (telling them which of our secrets or
# papers is missing is an internals leak).
NO_PROVIDER_REASON: Final = "no_number_provider"
PROVIDER_NOT_IMPLEMENTED_REASON: Final = "provider_not_implemented"
#: The engine this deployment runs sells no number of any class. A VENDOR fact.
NO_ENGINE_SUPPLY_REASON: Final = "engine_supplies_no_numbers"
#: **THE GO-LIVE GATE.** No written VNO/reseller status has been recorded, so no number
#: may be bought however ready the code is. A LEGAL fact, and the one an operator clears
#: deliberately by recording the instrument (`Settings.number_resale_authorization`).
NOT_AUTHORIZED_REASON: Final = "number_resale_not_authorized"

# **STILL FALSE, AND D-535 DID NOT FLIP IT — READ WHAT IT MEANS BEFORE ASSUMING IT
# SHOULD HAVE.** This constant marks whether a CARRIER-DIRECT provisioning adapter exists:
# a client of Exotel's or Plivo's own API, holding that carrier's auth id and auth token,
# asking a telecom operator for a number. None exists, none is wanted, and D-535 did not
# write one — the numbers this product now buys are bought THROUGH THE VOICE ENGINE, on
# the engine's own carrier account, over `VoiceEngine.provision_number`. So "this
# repository holds no telephony credential of any kind" stays true and stays load-bearing
# elsewhere (`engine/bolna.py`'s note on the transfer webhook, `agents/handoff.py`'s note
# on why a whisper is unachievable): both of those rest on the ABSENCE OF A CARRIER
# CREDENTIAL, which this names, and neither is affected by buying through the engine.
#
# It is therefore deliberately NOT consulted by `number_provisioning_capability()` any
# more. Two questions, two answers: "can we call a carrier directly" (no, and no plans)
# and "can this deployment supply a number at all" (the engine descriptor plus the written
# authorisation, below). Folding them into one boolean is what made the second question
# unaskable in the first place.
PROVISIONING_IMPLEMENTED: Final = False

#: The class of number this product buys, and the only one it may claim. 140 and 160 are
#: Indian DLT classes taken against a registered Principal Entity; nothing read at source
#: says this engine's buy endpoint can issue either, so a purchase never asserts one.
#: Named here rather than spelled at three call sites for D-103/D-105's reason.
PURCHASABLE_SERIES: Final = "standard"


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
    """THE selector. Every surface that cares asks this; nothing re-reads settings.

    ORDER IS THE VENDOR FACT FIRST, THE LEGAL FACT SECOND, and it is not arbitrary: an
    operator on a deployment whose engine sells nothing cannot fix that by finding a
    lawyer, and telling them "you are not authorised" would send them at the wrong
    problem. A deployment that CAN buy and MAY NOT is the interesting state, and it is the
    state every deployment is in today.
    """
    provider = (get_settings().number_provider or "").strip().lower()
    if provider and provider not in KNOWN_PROVIDERS:
        # A misconfiguration worth reporting even though nothing below depends on it: it
        # is the value a client's own-connection screen names back to them.
        return NumberProvisioningCapability(
            available=False,
            provider=provider,
            reason=f"{PROVIDER_NOT_IMPLEMENTED_REASON}:{provider}",
        )
    if not engine_capabilities().provisions(PURCHASABLE_SERIES):
        return NumberProvisioningCapability(
            available=False, provider=provider or None, reason=NO_ENGINE_SUPPLY_REASON
        )
    if not number_resale_authorization():
        return NumberProvisioningCapability(
            available=False, provider=provider or None, reason=NOT_AUTHORIZED_REASON
        )
    return NumberProvisioningCapability(
        available=True, provider=provider or None, reason=None, provisions_numbers=True
    )


def number_resale_authorization() -> str | None:
    """The written VNO/reseller status an operator has recorded, or None.

    ONE READER of the setting, so "is this deployment allowed to buy numbers" and "which
    document says so" cannot be answered from two places and disagree. Blank-stripped: a
    setting holding a space is not an authorisation, and a `.strip()` at each call site is
    how one of them eventually gets forgotten.
    """
    return (get_settings().number_resale_authorization or "").strip() or None


def assert_number_supply_authorized() -> None:
    """RAISE unless this deployment may lawfully buy a number. The one door.

    Called by every path that spends money at the vendor — search included, because a
    search screen that works and a buy button that refuses is a screen that teaches an
    operator the gate is a glitch. `campaigns/number_supply.py` calls it once per
    operation rather than trusting a screen to have asked.
    """
    capability = number_provisioning_capability()
    if capability.available:
        return
    raise provisioning_not_configured(capability.reason)


def number_purchase_available() -> bool:
    """The boolean a screen wants — the SAME selector the route uses, so a screen that
    offers the button and a route that refuses it cannot disagree."""
    return number_provisioning_capability().available


def provisioning_not_configured(reason: str | None) -> ProblemError:
    """The ONE deployment-side refusal, so every surface says it the same way.

    **THE DETAIL IS NOW PICKED FROM THE REASON, because the two refusals are not the same
    news and used to be told as one.** "This engine sells no numbers" is an operator's
    configuration problem; "we have no written reseller status" is a legal blocker that
    no amount of configuration clears, and reading the second as the first is how somebody
    tries to fix it by changing a setting. Neither text names a secret, a setting key or a
    vendor: the authored `reason` is logged for an operator and never returned.

    RFC-9457: the machine code is the LAST SEGMENT of `type`, and there is no `code` key.
    """
    log.warning("number_provisioning_unavailable", extra={"reason": reason or "unknown"})
    if reason == NOT_AUTHORIZED_REASON:
        return ProblemError(
            kind="dependency",
            code="number_resale_not_authorized",
            title="We cannot supply a number yet",
            detail=(
                "Supplying a telephone number in our own name needs a written "
                "authorisation from a licensed Indian operator, and that is not in place "
                "yet. Nothing has been bought and nothing has been charged."
            ),
            remediation=(
                "Record the written reseller authorisation before buying any number. "
                "Until it is in place, a client's calling number is a connection they "
                "take in their own name with an Indian operator and we connect it."
            ),
        )
    return ProblemError(
        kind="dependency",
        code="number_provisioning_not_configured",
        title="This deployment cannot buy a phone number",
        detail=(
            "The voice platform this deployment runs on does not sell telephone numbers, "
            "so none can be bought here."
        ),
        remediation=(
            "Connect a number the client already holds instead: they take it in their own "
            "name with an Indian operator — Exotel, Plivo or Vobiz — pass that operator's "
            "KYC and stay the subscriber of record, then send us the number and "
            "credentials they can withdraw at any time."
        ),
    )


def self_serve_purchase_refused() -> ProblemError:
    """What a CLIENT asking for a number is told, and why it is still no (D-535).

    The founder adopted an OPERATOR-LED supply, not a self-serve one, and the distinction
    is the playbook's own: §19 names "we provision the number for self-serve" as the
    unsafe shape. So this route refuses as it always did — what changed is that the old
    copy ("Calevate does not sell, rent or provision telephone numbers") is no longer
    TRUE, and a refusal that is not true teaches a client something they will repeat to
    their carrier.

    It names both routes forward, because both are real: their own connection, or ours
    arranged through their account manager. It promises no price and no timeline — neither
    is a fact this repository holds.
    """
    return ProblemError.business_rule(
        "number_purchase_is_operator_led",
        (
            "A phone number cannot be bought from this screen. Numbers are arranged with "
            "your account manager as part of setting your agent up."
        ),
        remediation=(
            "Talk to us and we will arrange the number, or bring one you already hold: "
            "take the connection in your own name with an Indian operator, pass their "
            "KYC, and send us the number and credentials you can withdraw at any time."
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
    "NOT_AUTHORIZED_REASON",
    "NO_ENGINE_SUPPLY_REASON",
    "NO_PROVIDER_REASON",
    "PROVIDER_NOT_IMPLEMENTED_REASON",
    "PROVISIONING_IMPLEMENTED",
    "PURCHASABLE_SERIES",
    "NumberProvisioningCapability",
    "assert_kyc_verified_for_provisioning",
    "assert_number_supply_authorized",
    "number_provisioning_capability",
    "number_purchase_available",
    "number_resale_authorization",
    "provisioning_not_configured",
    "self_serve_purchase_refused",
]
