"""Operator-attested model prices — the surface the founder types a vendor price into (§5).

    GET  /v1/ops/model-prices               every catalogue model: provider, reference
                                             price, attested price (or "needs a price"),
                                             offerability — AND the two VOICE tiers, the
                                             same three questions one vendor further down
    POST /v1/ops/model-prices/{model}       attest a model price; step-up
                                             `attest_model_price:<model>`
    POST /v1/ops/model-prices/tts/{provider} attest a VOICE provider's price; step-up
                                             `attest_tts_price:<provider>`

**WHY THE VOICE PRICE IS ON THIS PANEL AND NOT ITS OWN** (D-547, plan §F4: *"the model
pricing panel gains the Cartesia TTS attestation row"*). It is the same act — an operator
reading a figure off a vendor invoice this deployment cannot fetch, putting their name to
it, and thereby making a tier offerable (hard rule 7) — performed by the same person, with
the same permission, the same step-up discipline and the same append-only effective-dated
history. A second router would have been a second panel for one job, and the operator who
attested a model price and then could not find where the voice one lived would be the cost.
The two are separate LISTS in one response, never one merged list: a model has tokens and a
voice has characters, and a column that meant either would be a unit nobody could reconcile.

**THE ADMIN CONSOLE NAMES THE VENDOR, AND IT IS THE ONE SURFACE THAT DOES.** A client reads
"Clear" and "Studio" (`billing/rates.voice_tier_label`) and never a vendor name; an operator
reconciling a Cartesia invoice must see `cartesia`, because that is what the invoice says.
So `TtsPriceOut` carries BOTH — `provider` for the invoice, `tier_label` for the sentence a
client would read — and neither is derived in the browser.

Its own router rather than more routes on `config_routes.py`, for the reason that file's
sibling gives: a price is not a `Settings` field — it is effective-dated, append-only, and
resolved from the database at render time rather than layered onto `Settings` — so it has a
different write shape (POST a new dated row, never a conditional PUT over a revision) and a
different reader. Same realm, same permission, same audit-in-transaction discipline.

WHY `platform:config` AND NOT `platform:secrets`. A price is configuration, not a
credential: it is visible, revertible (by a superseding attestation) and carries no secret.
It gates on `platform:config` like the config panel — both are superadmin-only
(`core/rbac.SUPERADMIN_ONLY_PERMISSIONS`), so "only the super admin reaches this panel"
holds either way, and the narrower `platform:secrets` is reserved for the surface that can
point the platform at another vendor account.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Final, cast

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Path, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.voice_offer import cartesia_credential_installed, default_tts_price_is_billable
from apps.api.agents.voices import CARTESIA_TTS_MODEL, DEFAULT_TTS_MODEL
from apps.api.billing.plans import parse_billing_month
from apps.api.billing.rates import VoiceTier, voice_tier_label
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import global_db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.core.settings import get_settings
from apps.api.core.stepup import StepUpGate
from apps.api.ops.model_pricing import (
    TTS_PROVIDERS,
    AttestedModelPrice,
    ModelOfferability,
    TtsPlanFeeAttestation,
    TtsPriceAttestation,
    attest_price,
    attest_tts_plan_fee,
    attest_tts_price,
    attested_model_prices,
    attested_tts_prices,
    model_offerability,
    reference_price,
    reference_tts_plan_fee,
    reference_tts_price,
    tts_price_is_billable,
)
from apps.api.ops.pricing_snapshot import refresh_pricing_snapshot

router = APIRouter(prefix="/v1/ops/model-prices", tags=["ops"])

#: THE VOICE PRICE'S OWN PREFIX, in this file rather than its own module.
#:
#: The two are ONE PANEL and one act (see the module docstring), so the rows, the response
#: model and the money validator are shared — splitting the file would put half of one
#: screen's contract in each. But the WRITE is not a model price and must not be addressed
#: as one: `POST /v1/ops/model-prices/tts/cartesia` reads as a model called `tts`, and the
#: console posts to `/v1/ops/tts-prices/{provider}`
#: (`apps/web/src/app/admin/ops/ttsPricing.ts:OPS_TTS_PRICES_PATH`). Two routers, one
#: module, both mounted in `apps/api/main.py`.
tts_router = APIRouter(prefix="/v1/ops/tts-prices", tags=["ops"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]
PriceOperator = Annotated[Principal, Depends(requires("platform:config", realm="admin"))]

# A model identifier on the wire. Bounded because it is interpolated into a step-up string
# and an audit summary and is attacker-controlled on any surface — the character class every
# `LLM_MODELS` key uses (lower-case letters, digits, dots and hyphens). NOT an allow-list of
# known models: the service refuses an unknown one by name, and a second copy of the
# catalogue here is the drift this slice avoids.
ModelId = Annotated[str, Path(max_length=64, pattern=r"^[a-z0-9][a-z0-9.\-]*$")]

# A voice provider on the wire, bounded and character-classed for `ModelId`'s reason: it is
# interpolated into a step-up string and an audit summary. NOT an allow-list of the two
# known providers — `attest_tts_price` refuses an unknown one by name, and a second copy of
# that vocabulary here is the drift this route avoids.
TtsProviderId = Annotated[str, Path(max_length=32, pattern=r"^[a-z][a-z0-9_]*$")]

# The widest a price can be and still fit `NUMERIC(12,6)`: six integer digits. Shared by
# both attestations because both columns are that type — a figure at or above a million
# (dollars per million tokens, or rupees per thousand characters) is not a typo this API
# should try to store.
_MAX_PRICE = Decimal("1000000")


def tts_attest_confirmation(provider: str) -> str:
    """The step-up string for attesting ONE voice provider's price.

    A named function with a test pinning the literal, exactly as `attest_confirmation` is
    one, and bound to the PROVIDER for the same reason: a header captured while pricing
    Sarvam cannot be replayed to price Cartesia, whose figure is the one that turns a whole
    tier on.
    """
    return f"attest_tts_price:{provider}"


#: The widest a MONTHLY PLAN FEE can be and still fit `NUMERIC(12,2)`: ten integer digits.
#: A voice-synthesis plan at or above ₹10,000,000,000 a month is not a figure this API
#: should try to store, and the column could not hold it anyway.
_MAX_PLAN_FEE = Decimal("10000000000")


def tts_plan_fee_confirmation(provider: str, month: str) -> str:
    """The step-up string for attesting ONE vendor's fee for ONE month.

    Bound to BOTH, where its two neighbours are bound to one thing each, and the second
    binding is the one that matters: a header captured while attesting September's invoice
    must not be replayable to restate October's. A named function with a test pinning the
    literal, because it is an ops procedure a runbook prints.
    """
    return f"attest_tts_plan_fee:{provider}:{month}"


def attest_confirmation(model: str) -> str:
    """The step-up string for attesting ONE model's price.

    A named function with a test pinning the literal, like `config_confirmation` and
    `secret_confirmation`: it is an ops procedure a runbook prints. Bound to the MODEL, so a
    header captured for pricing gpt-4o-mini cannot be replayed to reprice gpt-5.6-luna.
    """
    return f"attest_model_price:{model}"


def _money(
    field_name: str,
    raw: str,
    *,
    unit: str = "USD per million tokens",
    maximum: Decimal = _MAX_PRICE,
    decimals: int = 6,
) -> Decimal:
    """A money string to a `Decimal`, or a boundary refusal. Never `float(...)`.

    `unit` names what the figure IS in every message, because the callers price different
    things — dollars per million tokens, rupees per thousand characters, rupees for a whole
    month — and an operator told "must be greater than zero" about the wrong quantity will
    re-enter the wrong number.

    `maximum` and `decimals` DEFAULT to the two price columns' shape, which is not a
    coincidence: both are `NUMERIC(12,6)`, so six integer digits and six decimals is a fact
    about that store. They are parameters because the PLAN FEE is `NUMERIC(12,2)` — an
    invoice is quoted to the paisa, there is nothing to divide — and accepting six decimals
    there would let Postgres silently ROUND a figure an operator typed off a bill. A
    refusal that names the field is the only honest answer to a value the column cannot
    hold exactly.

    Hard rule 7 does not stop at the database: the value arrives as a STRING and becomes a
    `Decimal` directly, so it never passes through a binary float. A non-numeric value, a
    NaN/Inf, a negative, an out-of-range or an over-precise one is refused HERE with the
    field named, rather than surfacing as a NUMERIC overflow from Postgres.
    """
    try:
        value = Decimal(raw.strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field_name} must be a decimal number of {unit}") from None
    if not value.is_finite():
        raise ValueError(f"{field_name} must be a finite number")
    if value <= 0:
        # Not "> 0 for tidiness": a zero (or negative) attested price bills every minute on
        # the model at nothing while looking like a working leg — `billing/rates
        # .LlmPriceAttestation` refuses it for the same reason, and the two must agree or an
        # accepted zero would crash the snapshot that feeds billing.
        raise ValueError(f"{field_name} must be greater than zero (a zero bills nothing)")
    if value >= maximum:
        raise ValueError(f"{field_name} is implausibly large for a figure in {unit}")
    # `exponent` is `int` for a finite Decimal (guarded above) but typed as
    # `int | Literal['n','N','F']` for the NaN/Inf cases — `isinstance` narrows it for the
    # type checker and is a no-op at runtime here.
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and -exponent > decimals:
        raise ValueError(
            f"{field_name} has more than {decimals} decimal places, which this store cannot hold"
        )
    return value


class ModelPriceOut(BaseModel):
    """One catalogue model, as the pricing panel renders it.

    MONEY IS A STRING END TO END (hard rule 7): a JSON float cannot hold a per-token price
    exactly, and a value that reaches a browser as `0.15000000000000002` is one nobody can
    reconcile against an invoice. `null` where a model has never been attested — a real
    state the console renders as "needs a price", distinct from a zero.

    NO FIELD CARRIES A DEFAULT, the same rule the config and secret panels follow: every
    fact the console must trust is required on the wire, and `null` is used where the answer
    genuinely has no value.
    """

    model_config = ConfigDict(extra="forbid")

    model: str
    provider: str
    #: The founder's offerability rule, split so the console can say WHICH half is missing.
    credential_installed: bool
    price_attested: bool
    #: `selectable AND credential_installed AND price_billable` — the whole rule, where
    #: this used to answer for the last two. A screen that reported the partial answer as
    #: "available to customers" told the founder that a model withheld on merit would
    #: become available once priced.
    offerable: bool
    #: `null` when this repository permits the model on merit. Otherwise the GROUND, in the
    #: catalogue's own words: attesting a price will not change it, and the reason is
    #: usually the more useful fact (dead air mid-call, a 10x cost tier, a vendor page
    #: nobody has read). `LlmModelSpec.withdrawn_reason`.
    withheld_reason: str | None
    #: The attested figures, USD per million tokens, as strings. `null` until attested.
    input_usd_per_mtok: str | None
    output_usd_per_mtok: str | None
    effective_from: str | None
    attested_at: str | None
    attested_by: str | None
    source_note: str | None
    #: The CATALOGUE's own price, pre-filled into the form GREYED. `reference_verified` is
    #: True only for the legs D-410 read first-hand (Azure); for OpenAI/Google it is False
    #: and the label reads "unverified — confirm against your vendor invoice".
    reference_input_usd_per_mtok: str
    reference_output_usd_per_mtok: str
    reference_verified: bool


class TtsPriceOut(BaseModel):
    """One VOICE provider's price, as the same panel renders it (D-547).

    MONEY IS A STRING END TO END and NO FIELD CARRIES A DEFAULT — `ModelPriceOut`'s two
    rules, for its two reasons. `null` where nobody has attested, which is a real state the
    console renders as "needs a price" and is not a zero.

    The field names are the console's own seam
    (`apps/web/src/app/admin/ops/ttsPricing.ts::asTtsPrice`), which validates every one of
    them and renders a stated absence rather than a default: a `price_billable` this
    response failed to send would otherwise read as "sellable" on a tier whose every minute
    meters as free.
    """

    model_config = ConfigDict(extra="forbid")

    #: THE VENDOR'S OWN NAME, because this is the surface where an operator reconciles a
    #: vendor invoice. Every client-facing surface says `tier_label` instead.
    provider: str
    #: What a CLIENT calls this tier — `billing/rates.voice_tier_label`, crossing the wire
    #: rather than being typed in the browser, so the console and the client's own screen
    #: cannot come to call one tier two things.
    tier_label: str
    #: The synthesizer model this leg speaks with (`bulbul:v3`, `sonic-3.5`) — the fact
    #: that makes a price checkable against a vendor's price list, which is quoted per
    #: model rather than per company.
    tts_model: str
    #: Is a key for this vendor installed on this deployment? Ground 1 of the picker's
    #: three (`agents/voice_offer`), reported here because a price attested against a
    #: vendor we hold no key for buys nothing.
    credential_installed: bool
    #: Has an operator attested a figure — distinct from `price_billable`, which is True
    #: for the engine-metered Sarvam leg with no attestation at all.
    price_attested: bool
    #: May a minute on this tier be METERED at a cost right now — THE one door,
    #: `ops/model_pricing.tts_price_is_billable`.
    price_billable: bool
    #: `credential_installed AND price_billable`: may this tier be sold today. The
    #: platform-wide Cartesia agent CAP (Q10) is deliberately not folded in — it is a fact
    #: about how many agents are already on the tier, not about the tier, and the picker
    #: reports it per agent (`voice_offer.cartesia_cap_reached_reason`).
    offerable: bool
    #: WHY THIS LEG NEEDS NO ATTESTATION, when it needs none — `null` when it does need
    #: one. A Sarvam row with an empty price field and no explanation reads as an
    #: outstanding job; it is not one, and the console prints this sentence instead.
    billable_without_attestation_reason: str | None
    #: The attested figure, rupees per 1,000 characters, as a string. `null` until attested.
    inr_per_1k_chars: str | None
    effective_from: str | None
    attested_at: str | None
    attested_by: str | None
    source_note: str | None
    #: THIS TREE'S OWN figure, pre-filled into the form GREYED and labelled "confirm
    #: against your vendor invoice". Never authoritative: Sarvam's is a published list rate
    #: and Cartesia's is the plan fee divided by its allotment, which is why hard rule 7
    #: keeps both out of `unit_cost_paid` (`ops/model_pricing.reference_tts_price`).
    reference_inr_per_1k_chars: str


class ModelPricesOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prices: list[ModelPriceOut]
    #: The VOICE tiers, on the same read as the models. One row per member of
    #: `ops/model_pricing.TTS_PROVIDERS` — two — in catalogue order, never a shorter list:
    #: a panel that omitted the tier nobody has priced would hide the one row that needs
    #: an operator.
    tts_prices: list[TtsPriceOut]
    #: The instant the attested prices were resolved at (now). A re-render of a past month
    #: would resolve at that month's instant; this surface always shows what is live TODAY.
    as_of: str


class ModelPriceAttestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: USD per MILLION input tokens, as a decimal STRING. Validated to a `Decimal` at the
    #: boundary; never a JSON number.
    input_usd_per_mtok: str
    output_usd_per_mtok: str
    #: When this price becomes authoritative. Omit for "from now on"; supply an earlier
    #: instant to correct the record for a period already elapsed. MUST be timezone-aware.
    effective_from: datetime | None = None
    #: WHERE the figure came from, in the operator's words — the evidence that makes this an
    #: attestation and not a guess, and the reason recorded in `audit_log`.
    source_note: str = Field(min_length=3, max_length=500)

    @field_validator("source_note")
    @classmethod
    def _not_whitespace(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 3:
            raise ValueError("say where this price came from — a vendor invoice or pricing page")
        return stripped

    @field_validator("effective_from")
    @classmethod
    def _tz_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError(
                "effective_from must carry a timezone (send an ISO instant with an offset)"
            )
        return value


class ModelPriceWriteOut(BaseModel):
    """The model as it now stands, plus the instant the rest of the list was resolved at."""

    model_config = ConfigDict(extra="forbid")

    price: ModelPriceOut
    as_of: str


class TtsPriceAttestIn(BaseModel):
    """One voice provider's price, as an operator types it off an invoice.

    `ModelPriceAttestIn` with two words changed — rupees per 1,000 CHARACTERS instead of
    dollars per million TOKENS — and the same three rules: money as a decimal string,
    `effective_from` optional but timezone-aware when given, evidence required.
    """

    model_config = ConfigDict(extra="forbid")

    #: ₹ per 1,000 CHARACTERS, as a decimal STRING. Validated to a `Decimal` at the
    #: boundary; never a JSON number (hard rule 7).
    inr_per_1k_chars: str
    #: When this price becomes authoritative. Omit for "from now on"; supply an earlier
    #: instant to correct the record for a period already elapsed. MUST be timezone-aware.
    effective_from: datetime | None = None
    #: WHICH PLAN, WHICH PERIOD, AND THE DIVISION — "Cartesia Startup plan, invoice
    #: 2026-09, ₹4,312 / 1.25M characters". The figure is the plan's MARGINAL rate inside
    #: its allotment, so a reader a year later has to be able to tell which regime it
    #: belongs to; this is the field that says so, and it is the reason recorded in
    #: `audit_log`.
    source_note: str = Field(min_length=3, max_length=500)

    @field_validator("source_note")
    @classmethod
    def _not_whitespace(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 3:
            raise ValueError(
                "say where this price came from — name the plan, the invoice period and "
                "the characters it buys"
            )
        return stripped

    @field_validator("effective_from")
    @classmethod
    def _tz_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError(
                "effective_from must carry a timezone (send an ISO instant with an offset)"
            )
        return value


class TtsPriceWriteOut(BaseModel):
    """The voice tier as it now stands, plus the instant it was resolved at."""

    model_config = ConfigDict(extra="forbid")

    price: TtsPriceOut
    as_of: str


class TtsPlanFeeAttestIn(BaseModel):
    """What a voice vendor BILLED US for one month, as an operator types it off the invoice.

    `TtsPriceAttestIn`'s three rules — money as a decimal string, `effective_from` optional
    but timezone-aware when given, evidence required — with the subject changed. THE FIGURE
    IS THE WHOLE MONTH, not a rate: the division by the allotment is the OTHER
    attestation's, and asking for it twice is how the two come to disagree.
    """

    model_config = ConfigDict(extra="forbid")

    #: The IST billing month the invoice covers, `YYYY-MM`. Validated by
    #: `billing/plans.parse_billing_month` at the handler — the one parser this product has
    #: for a billing month, so the panel and the spend board cannot come to disagree about
    #: what `2026-9` means.
    month: str = Field(max_length=7)
    #: RUPEES FOR THE WHOLE MONTH, as a decimal STRING, never a JSON number (hard rule 7).
    #: The column is `NUMERIC(12,2)` — an invoice is quoted to the paisa — so a third
    #: decimal is refused rather than silently rounded.
    plan_inr: str
    #: When this attestation becomes authoritative. Omit for "from now on"; supply an
    #: earlier instant to correct the record as of a past moment. MUST be timezone-aware.
    #: It is NOT the month: a September invoice is normally attested in October, and
    #: resolving the fee at September's own last instant would make it invisible.
    effective_from: datetime | None = None
    #: WHICH PLAN AND WHICH INVOICE — "Cartesia Startup plan, invoice INV-2026-09-014,
    #: ₹4,312". It is the evidence that makes this an attestation rather than a guess, the
    #: only thing that lets a reader a year later re-check the figure rather than re-make
    #: it, and the reason recorded in `audit_log`.
    source_note: str = Field(min_length=3, max_length=500)

    @field_validator("source_note")
    @classmethod
    def _not_whitespace(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 3:
            raise ValueError("name the plan and the invoice this figure came off")
        return stripped

    @field_validator("effective_from")
    @classmethod
    def _tz_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError(
                "effective_from must carry a timezone (send an ISO instant with an offset)"
            )
        return value


class TtsPlanFeeOut(BaseModel):
    """One attested monthly plan fee, as the panel renders it back.

    MONEY IS A STRING END TO END and NO FIELD CARRIES A DEFAULT — `ModelPriceOut`'s two
    rules for its two reasons. What this row does NOT carry is what the month ATTRIBUTED:
    that is a cross-tenant sum of `usage_events` and it belongs to the spend board
    (`GET /v1/admin/spend`'s `tts_plan`), which reads every client's rows inside that
    client's own RLS scope. Publishing it from here would mean a second computation of one
    figure, and the two would come to disagree about a month.
    """

    model_config = ConfigDict(extra="forbid")

    #: THE VENDOR'S OWN NAME — this is the surface where an operator reconciles an invoice.
    provider: str
    #: What a CLIENT calls the same tier, served rather than typed in the browser.
    tier_label: str
    month: str
    plan_inr: str
    effective_from: str
    attested_at: str
    attested_by: str
    source_note: str
    #: THIS TREE'S OWN monthly figure, pre-filled into the form GREYED and labelled
    #: "confirm against your vendor invoice". Never authoritative: hard rule 7 gives a
    #: catalogue figure no path to a cost we report as paid, and this one is $49 at a
    #: relayed conversion for a plan nobody has yet bought
    #: (`ops/model_pricing.reference_tts_plan_fee`).
    reference_plan_inr: str


class TtsPlanFeeWriteOut(BaseModel):
    """The fee as it now stands, plus the instant the write was made at."""

    model_config = ConfigDict(extra="forbid")

    plan_fee: TtsPlanFeeOut
    as_of: str


def _plan_fee_row(attested: TtsPlanFeeAttestation) -> TtsPlanFeeOut:
    return TtsPlanFeeOut(
        provider=attested.provider,
        tier_label=voice_tier_label(cast("VoiceTier", attested.provider)),
        month=attested.month,
        plan_inr=str(attested.plan_inr),
        effective_from=attested.effective_from.isoformat(),
        attested_at=attested.attested_at.isoformat(),
        attested_by=attested.attested_by,
        source_note=attested.source_note,
        reference_plan_inr=str(reference_tts_plan_fee(attested.provider)),
    )


def _row(
    offer: ModelOfferability,
    attested: AttestedModelPrice | None,
) -> ModelPriceOut:
    ref_in, ref_out, ref_verified = reference_price(offer.model)
    return ModelPriceOut(
        model=offer.model,
        provider=offer.provider,
        credential_installed=offer.credential_installed,
        price_attested=offer.price_attested,
        offerable=offer.offerable,
        withheld_reason=offer.withheld_reason,
        input_usd_per_mtok=str(attested.input_usd_per_mtok) if attested else None,
        output_usd_per_mtok=str(attested.output_usd_per_mtok) if attested else None,
        effective_from=attested.effective_from.isoformat() if attested else None,
        attested_at=attested.attested_at.isoformat() if attested else None,
        attested_by=attested.attested_by if attested else None,
        source_note=attested.source_note if attested else None,
        reference_input_usd_per_mtok=str(ref_in),
        reference_output_usd_per_mtok=str(ref_out),
        reference_verified=ref_verified,
    )


async def _rows(session: AsyncSession, *, at: datetime) -> list[ModelPriceOut]:
    offers = await model_offerability(session, at=at)
    attested = await attested_model_prices(session, at=at)
    return [_row(offers[model], attested.get(model)) for model in sorted(offers)]


#: The synthesizer model each leg speaks with. Both values are named constants in the voice
#: catalogue — `agents/voices` declares one model per provider and says why (`TtsModel`) —
#: so this maps the two rather than spelling either string here. It is not derived from
#: `CATALOG` because a provider with no personas listed yet (Cartesia, until Q1 is answered)
#: would then have no model to report on a row whose whole purpose is to get its price
#: attested before those personas arrive.
_TTS_MODEL: Final[dict[str, str]] = {
    "sarvam": DEFAULT_TTS_MODEL,
    "cartesia": CARTESIA_TTS_MODEL,
}

#: Why the Sarvam leg is billable with nothing attested. The console renders it where the
#: attestation form would otherwise be, so an operator does not go looking for an invoice
#: that does not exist. It is the same fact `tts_price_is_billable`'s docstring states, and
#: it is NOT an exemption from hard rule 7 — the leg has a measured cost on every row.
BILLABLE_WITHOUT_ATTESTATION_REASON: Final = (
    "the engine bills us for this synthesizer leg and reports what it charged on every "
    "call, so this tier already has a measured cost on every usage row — there is no "
    "invoice of ours to divide and nothing here to confirm"
)


def _tts_credential_installed(provider: str) -> bool:
    """Is a key for this voice vendor installed here?

    Cartesia goes through `agents/voice_offer.cartesia_credential_installed` — the picker's
    own ground 1, so the panel and the picker cannot disagree about a key. Sarvam has no
    such function because no ground of the picker depends on it (the engine holds that leg),
    so it is read the same way, off the settings the ops console overlays its encrypted
    store onto, rather than inventing a second notion of installed.
    """
    if provider == "cartesia":
        return cartesia_credential_installed()
    return bool((get_settings().sarvam_api_key or "").strip())


def _tts_row(
    provider: str,
    attested: TtsPriceAttestation | None,
    *,
    billable: bool,
    credential_installed: bool,
) -> TtsPriceOut:
    # "Would this tier be unbillable with nothing attested?" — asked of the one function
    # that states which legs carry a cost of their own (`default_tts_price_is_billable`,
    # the picker's own pre-store answer), never spelled `provider != "sarvam"` here. A
    # third provider then arrives in one place rather than two.
    tier = cast("VoiceTier", provider)
    needs = not default_tts_price_is_billable(tier)
    return TtsPriceOut(
        provider=provider,
        tier_label=voice_tier_label(tier),
        tts_model=_TTS_MODEL[provider],
        credential_installed=credential_installed,
        price_attested=attested is not None,
        price_billable=billable,
        offerable=credential_installed and billable,
        billable_without_attestation_reason=(
            None if needs else BILLABLE_WITHOUT_ATTESTATION_REASON
        ),
        inr_per_1k_chars=str(attested.inr_per_1k_chars) if attested else None,
        effective_from=attested.effective_from.isoformat() if attested else None,
        attested_at=attested.attested_at.isoformat() if attested else None,
        attested_by=attested.attested_by if attested else None,
        source_note=attested.source_note if attested else None,
        reference_inr_per_1k_chars=str(reference_tts_price(provider)),
    )


async def _tts_rows(session: AsyncSession, *, at: datetime) -> list[TtsPriceOut]:
    """Both voice tiers, in catalogue order, each with its verdict.

    The credential is read from settings (the ops console's encrypted store is overlaid
    onto them), which is where the engine adapter would read the key from — never a second
    notion of "installed".

    ONE read of the price table for both rows, and the billable verdict comes from
    `tts_price_is_billable` — the one door — rather than from `provider in attested`, which
    would be a second spelling of the rule and would report the Sarvam tier as unbillable
    the moment somebody read this file instead of that one.
    """
    attested = await attested_tts_prices(session, at=at)
    return [
        _tts_row(
            provider,
            attested.get(provider),
            billable=await tts_price_is_billable(session, provider=provider, at=at),
            credential_installed=_tts_credential_installed(provider),
        )
        for provider in TTS_PROVIDERS
    ]


@router.get(
    "",
    response_model=ModelPricesOut,
    openapi_extra=permission_meta("platform:config"),
    summary="Every model's and every voice tier's reference price, attested price and status",
    description=(
        "Lists every model in the catalogue with its declared leg, the catalogue's own "
        "(possibly unverified) reference price, the operator-attested price if one exists, "
        "and whether the model is offerable yet — which needs BOTH its provider credential "
        "installed AND a price attested. A model with no attested price is shown as needing "
        "one; the reference price is a pre-fill to confirm against a vendor invoice, never "
        "the authoritative value. `tts_prices` answers the same three questions for the two "
        "VOICE tiers, whose unit is rupees per 1,000 characters rather than dollars per "
        "million tokens; a tier with no attested price offers no voices at all."
    ),
)
async def list_model_prices(session: GlobalSession, _: PriceOperator) -> ModelPricesOut:
    at = datetime.now(UTC)
    return ModelPricesOut(
        prices=await _rows(session, at=at),
        tts_prices=await _tts_rows(session, at=at),
        as_of=at.isoformat(),
    )


@router.post(
    "/{model}",
    response_model=ModelPriceWriteOut,
    openapi_extra=permission_meta("platform:config"),
    summary="Attest one model's vendor price (step-up confirmed, audited)",
    description=(
        "Records a price you read off your own vendor console or invoice as a NEW "
        "effective-dated row — a correction is a later attestation, never an edit, so a "
        "re-rendered invoice resolves the price that was live in its month. Requires "
        "`X-Confirm-Action: attest_model_price:<model>`. Money is sent as a decimal string "
        "(USD per million tokens), never a float. This is what lets a model whose catalogue "
        "price is unverified become offerable."
    ),
)
async def attest_model_price(
    payload: ModelPriceAttestIn,
    session: GlobalSession,
    request: Request,
    tasks: BackgroundTasks,
    principal: PriceOperator,
    model: ModelId,
    # Resolved BEFORE this handler body runs, so the session read cannot happen inside an
    # open transaction — `core/stepup.py` on `max_overflow=0`.
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> ModelPriceWriteOut:
    """One attestation in, one audit row, in the same transaction."""
    step_up.require(x_confirm_action, attest_confirmation(model))
    if principal.user_id is None:
        # `attested_by` is NOT NULL and references `admin_users`: every price was typed by a
        # person. An admin principal always has one; refusing explicitly turns an impossible
        # state into a sentence rather than an integrity error rendered as a 500.
        raise ProblemError(
            kind="auth",
            code="model_price_actor_unknown",
            title="This session has no admin identity",
            detail="A price attestation has to be attributable to an operator.",
        )
    try:
        input_price = _money("input_usd_per_mtok", payload.input_usd_per_mtok)
        output_price = _money("output_usd_per_mtok", payload.output_usd_per_mtok)
    except ValueError as exc:
        raise ProblemError(
            kind="validation",
            code="model_price_invalid",
            title="That is not a valid price",
            detail=str(exc),
            remediation="Type USD per million tokens with a decimal point, like 0.15.",
        ) from None

    effective_from = payload.effective_from or datetime.now(UTC)
    attested = await attest_price(
        session,
        model=model,
        input_usd_per_mtok=input_price,
        output_usd_per_mtok=output_price,
        effective_from=effective_from,
        source_note=payload.source_note,
        actor_id=principal.user_id,
    )
    await write_audit(
        session,
        action="platform.model_price_attested",
        actor=principal,
        object_type="platform_model_prices",
        object_id=model,
        ip=client_request_ip(request),
        # The change itself: the model, the two figures, the instant it takes effect, and
        # the operator's stated evidence. No secret, no PII.
        summary={
            "model": model,
            "input_usd_per_mtok": str(attested.input_usd_per_mtok),
            "output_usd_per_mtok": str(attested.output_usd_per_mtok),
            "effective_from": attested.effective_from.isoformat(),
            "source_note": attested.source_note,
        },
    )
    # Refresh the process snapshot AFTER the request's transaction commits, so the new
    # price reaches the billing seam and the picker on the next read rather than waiting a
    # full poll interval — the same background-task-after-commit shape config's `propagate`
    # uses, and survivable if it fails (the 30s poll is the guarantee, this only makes it
    # prompt).
    tasks.add_task(refresh_pricing_snapshot)
    at = datetime.now(UTC)
    offers = await model_offerability(session, at=at)
    current = (await attested_model_prices(session, at=at)).get(model)
    return ModelPriceWriteOut(price=_row(offers[model], current), as_of=at.isoformat())


@tts_router.post(
    "/{provider}",
    response_model=TtsPriceWriteOut,
    openapi_extra=permission_meta("platform:config"),
    summary="Attest one voice provider's TTS price (step-up confirmed, audited)",
    description=(
        "Records what a voice tier costs THIS account, read off your own vendor invoice, as "
        "a NEW effective-dated row — a correction is a later attestation, never an edit, so "
        "a month re-rendered next year resolves the figure its minutes were metered at. "
        "Requires `X-Confirm-Action: attest_tts_price:<provider>`. The figure is rupees per "
        "1,000 CHARACTERS as a decimal string, never a float: for a monthly plan it is the "
        "committed spend divided by the characters it buys, which is a division only "
        "somebody holding the invoice can do. Until it exists, every voice on that tier is "
        "refused by the picker, because an unpriced minute is unmetered spend rather than a "
        "free one."
    ),
)
async def attest_voice_price(
    payload: TtsPriceAttestIn,
    session: GlobalSession,
    request: Request,
    tasks: BackgroundTasks,
    principal: PriceOperator,
    provider: TtsProviderId,
    # Resolved BEFORE this handler body runs, so the session read cannot happen inside an
    # open transaction — `core/stepup.py` on `max_overflow=0`.
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> TtsPriceWriteOut:
    """One attestation in, one audit row, in the same transaction — `attest_model_price`."""
    step_up.require(x_confirm_action, tts_attest_confirmation(provider))
    if principal.user_id is None:
        # `attested_by` is NOT NULL and references `admin_users`: every price here was typed
        # by a person. Refusing explicitly turns an impossible state into a sentence rather
        # than an integrity error rendered as a 500.
        raise ProblemError(
            kind="auth",
            code="tts_price_actor_unknown",
            title="This session has no admin identity",
            detail="A price attestation has to be attributable to an operator.",
        )
    try:
        rate = _money(
            "inr_per_1k_chars", payload.inr_per_1k_chars, unit="rupees per 1,000 characters"
        )
    except ValueError as exc:
        raise ProblemError(
            kind="validation",
            code="tts_price_invalid",
            title="That is not a valid price",
            detail=str(exc),
            remediation=(
                "Type rupees per 1,000 characters with a decimal point, like 3.4496 — "
                "the plan's committed spend divided by the characters it buys."
            ),
        ) from None

    effective_from = payload.effective_from or datetime.now(UTC)
    attested = await attest_tts_price(
        session,
        provider=provider,
        inr_per_1k_chars=rate,
        effective_from=effective_from,
        source_note=payload.source_note,
        actor_id=principal.user_id,
    )
    await write_audit(
        session,
        action="platform.tts_price_attested",
        actor=principal,
        object_type="platform_tts_prices",
        object_id=provider,
        ip=client_request_ip(request),
        # The change itself: the vendor, the figure, the instant it takes effect and the
        # operator's stated evidence. No secret, no PII.
        summary={
            "provider": provider,
            "inr_per_1k_chars": str(attested.inr_per_1k_chars),
            "effective_from": attested.effective_from.isoformat(),
            "source_note": attested.source_note,
        },
    )
    # AFTER the request's transaction commits, so the new price reaches the VOICE PICKER
    # (`agents/voice_offer.tts_price_is_billable`, whose reader this snapshot feeds) on the
    # next render rather than a poll interval later — `attest_model_price`'s shape, and
    # survivable if it fails, because the 30s poll is the guarantee.
    tasks.add_task(refresh_pricing_snapshot)
    at = datetime.now(UTC)
    current = (await attested_tts_prices(session, at=at)).get(provider)
    return TtsPriceWriteOut(
        price=_tts_row(
            provider,
            current,
            billable=await tts_price_is_billable(session, provider=provider, at=at),
            credential_installed=_tts_credential_installed(provider),
        ),
        as_of=at.isoformat(),
    )


@tts_router.post(
    "/{provider}/plan-fee",
    response_model=TtsPlanFeeWriteOut,
    openapi_extra=permission_meta("platform:config"),
    summary="Attest what a voice vendor billed for one month (step-up confirmed, audited)",
    description=(
        "Records the MONTHLY PLAN FEE a voice vendor invoiced this account, read off that "
        "invoice, as a NEW dated row for one IST billing month — a correction is a later "
        "attestation for the same month, never an edit, so the record of what we believed "
        "we were billed survives the correction that superseded it. Requires "
        "`X-Confirm-Action: attest_tts_plan_fee:<provider>:<month>`, bound to both so a "
        "header captured for one month cannot restate another. The figure is rupees for "
        "the whole month as a decimal string, quoted to the paisa. It is NOT the "
        "per-character price beside it and is never an input to what a call is metered at: "
        "it is published on the spend board against what our own meter attributed, and "
        "their difference is the allotment nobody spoke into. Only vendors billed as a "
        "monthly plan can be attested — a vendor whose synthesizer leg the engine buys and "
        "reports on every call has no invoice of ours to divide."
    ),
)
async def attest_voice_plan_fee(
    payload: TtsPlanFeeAttestIn,
    session: GlobalSession,
    request: Request,
    principal: PriceOperator,
    provider: TtsProviderId,
    # Resolved BEFORE this handler body runs, so the session read cannot happen inside an
    # open transaction — `core/stepup.py` on `max_overflow=0`.
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> TtsPlanFeeWriteOut:
    """One attestation in, one audit row, in the same transaction — `attest_voice_price`.

    NO `refresh_pricing_snapshot` HERE, and the omission is deliberate rather than an
    oversight: that snapshot feeds the VOICE PICKER and the billing seam, and a plan fee
    reaches neither. It is read by the spend board, which queries the table on every
    render. A background refresh for a figure nothing cached would be a task that looks
    like wiring and does nothing.
    """
    # The one parser this product has for a billing month, BEFORE the step-up string is
    # built from it: a header confirming `2026-9` must not be accepted for a month that
    # spelling could never have named.
    parse_billing_month(payload.month)
    step_up.require(x_confirm_action, tts_plan_fee_confirmation(provider, payload.month))
    if principal.user_id is None:
        # `attested_by` is NOT NULL and references `admin_users`: every figure here was
        # typed by a person. Refusing explicitly turns an impossible state into a sentence
        # rather than an integrity error rendered as a 500.
        raise ProblemError(
            kind="auth",
            code="tts_plan_fee_actor_unknown",
            title="This session has no admin identity",
            detail="A plan-fee attestation has to be attributable to an operator.",
        )
    try:
        fee = _money(
            "plan_inr",
            payload.plan_inr,
            unit="rupees for the whole month",
            maximum=_MAX_PLAN_FEE,
            decimals=2,
        )
    except ValueError as exc:
        raise ProblemError(
            kind="validation",
            code="tts_plan_fee_invalid",
            title="That is not a valid plan fee",
            detail=str(exc),
            remediation=(
                "Type the invoice total in rupees with a decimal point, like 4312.00 — "
                "the whole month, to the paisa, not a per-character rate."
            ),
        ) from None

    attested = await attest_tts_plan_fee(
        session,
        provider=provider,
        month=payload.month,
        plan_inr=fee,
        effective_from=payload.effective_from or datetime.now(UTC),
        source_note=payload.source_note,
        actor_id=principal.user_id,
    )
    await write_audit(
        session,
        action="platform.tts_plan_fee_attested",
        actor=principal,
        object_type="platform_tts_plan_fees",
        # The vendor AND the month: an audit row naming only the vendor could not tell two
        # months' attestations apart, which is the whole subject of this table.
        object_id=f"{provider}:{payload.month}",
        ip=client_request_ip(request),
        # The change itself: the vendor, the month, the figure, the instant it takes effect
        # and the operator's stated evidence. No secret, no PII.
        summary={
            "provider": provider,
            "month": attested.month,
            "plan_inr": str(attested.plan_inr),
            "effective_from": attested.effective_from.isoformat(),
            "source_note": attested.source_note,
        },
    )
    return TtsPlanFeeWriteOut(plan_fee=_plan_fee_row(attested), as_of=datetime.now(UTC).isoformat())


__all__ = [
    "BILLABLE_WITHOUT_ATTESTATION_REASON",
    "attest_confirmation",
    "router",
    "tts_attest_confirmation",
    "tts_plan_fee_confirmation",
    "tts_router",
]
