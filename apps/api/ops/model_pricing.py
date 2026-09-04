"""Operator-attested model prices, and the offerability they gate (PLATFORM-CONFIG §5).

WHY THIS EXISTS, in one paragraph. Hard rule 7 does not have a REPORTED tier: a price is
the one vendor claim that reaches `unit_cost_paid`, so `calevate_shared.engine
.LlmModelSpec` refuses to make a model selectable on an unverified price. Every OpenAI and
Google pricing page is egress-blocked from this deployment, so no price for those two
declared legs (D-456) can ever be VERIFIED in the tree. The founder's own workflow supplies
the missing evidence: the AUTHORITATIVE billing price is a value they read off their own
vendor console or invoice and type into the ops panel — first-party evidence, and the only
figure true for THIS account (a Regional Standard deployment costs more than the Global
Standard list price the catalogue carries). `platform_model_prices` stores it, effective-
dated and append-only; this module reads and writes it.

## The two things this module answers

1. **What did a model cost at instant T** — `attested_model_prices(session, at=…)`, the
   reader the rate card consumes. Effective-dated so a re-rendered invoice resolves the
   price that was live in the month it is re-rendering, exactly as `billing/plans.py`
   resolves a plan at a month instant.
2. **May a model be offered** — `model_offerability` / `offerable_models`. The founder's
   rule: a model is offerable only when its provider credential is INSTALLED and its price
   is ATTESTED. This is the credential+attestation half; the catalogue lane's
   `agents/llm_models.available_models` composes it with the static `selectable` flag and
   the addressability of a deployment.

## Units: USD per MILLION tokens, matching the catalogue

`LlmPrice.input_usd_per_mtok` is USD/Mtok and `billing/rates.py` converts it to rupees at a
named FX rate. This module stays in the vendor's unit for the identical reason (hard rule
7): the vendor publishes dollars, the USD->INR rate MOVES (it is pulled every five
minutes, D-475), and a figure that has already multiplied the two cannot be re-derived
when either moves. Every value in and
out of here is a `Decimal`, never a float.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import cast, get_args

from calevate_shared.engine import LLM_MODELS, LlmProvider
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.ops.secret_service import read_secrets

# THE ONE READER OF THE THREE `azure_openai_*` CREDENTIAL FIELDS — the same import
# `agents/llm_models.py` and `agents/service.py` make, for the identical reason: "is the
# Azure leg configured" must have one answer, and a second read here would be a second
# definition of it.
from apps.workers.extraction import azure_credentials

#: Which `Settings` credential field installs the key for each declared LLM leg.
#:
#: THE ONE PLACE this mapping lives. `LlmProvider` is the engine's closed vocabulary and
#: the value is a `platform_secrets` key name — relating the two is a platform concern, so
#: it is stated here once rather than re-derived at each call site. The engine's OWN
#: credential-store entry names (`AZURE_OPENAI_API_KEY`, `OPENAI`, `GOOGLE`) are a different
#: thing and stay in `engine/bolna.py` (hard rule 2): those are what the engine reads, this
#: is where OUR store keeps the value the platform installs.
#:
#: Exhaustive over `LlmProvider` on purpose: adding a fourth leg to that Literal without a
#: credential here would raise `KeyError` in `_provider_installed` rather than silently
#: reporting the leg as un-credentialed, and `tests/model_pricing_test.py` pins the mapping
#: against `get_args(LlmProvider)` so the gap is a failed test, not a wrong screen.
PROVIDER_CREDENTIAL: dict[LlmProvider, str] = {
    "azure_openai": "azure_openai_api_key",
    "openai": "openai_api_key",
    "google": "gemini_api_key",
}


@dataclass(frozen=True, slots=True)
class AttestedModelPrice:
    """One model's attested vendor price, with its provenance.

    `input_usd_per_mtok` / `output_usd_per_mtok` are USD per MILLION tokens — the shape
    `calevate_shared.engine.LlmPrice` publishes, so a caller can substitute this for a
    catalogue price field by field. Frozen because a price that reached a caller must not be
    mutable underneath it, and it carries its own provenance so the next reader inherits the
    evidence (`source_note`) rather than the conclusion.
    """

    model: str
    input_usd_per_mtok: Decimal
    output_usd_per_mtok: Decimal
    effective_from: datetime
    attested_at: datetime
    #: The operator, by display name where there is one and by id otherwise — never empty,
    #: because the billing seam refuses an unattributed attestation (D-31/D-32).
    attested_by: str
    source_note: str


async def attested_model_prices(
    session: AsyncSession, *, at: datetime
) -> dict[str, AttestedModelPrice]:
    """Every model's price effective at instant `at`, keyed by model identifier.

    THE READER THE RATE CARD CONSUMES. For each model it returns the attestation with the
    greatest `effective_from <= at` — the price that was live at that instant — so a
    re-rendered invoice resolves the figure it was struck at rather than today's. A model
    with no attestation on or before `at` is absent from the mapping; the caller decides
    what an unpriced model means (the rate card refuses to bill one, the console shows it as
    "needs a price").

    `at` MUST be timezone-aware — it is compared against `effective_from`, which is
    `timestamptz` — and there is no default: which instant to price at is the caller's fact
    (now, while a month is open; the month's last instant once it is closed —
    `billing/plans.month_pricing_instant`), and a default of `now()` here would silently
    re-price a closed month at today's terms, the exact defect
    `late_call_prices_at_its_own_month_test` exists for.

    ONE ROUND TRIP: `DISTINCT ON (model) … ORDER BY model, effective_from DESC` over the
    index, the same shape `secret_service.resolve_secrets` uses to pick the current version
    of each key.
    """
    rows = (
        await session.execute(
            text(
                "SELECT DISTINCT ON (p.model) p.model, p.input_usd_per_mtok, "
                "p.output_usd_per_mtok, p.effective_from, p.attested_at, "
                # COALESCE to the id text, never NULL: `attested_by` is NOT NULL in the
                # table, but `admin_users.name` can be, and the billing seam
                # (`LlmPriceAttestation`) refuses an empty attester — so the operator is
                # always named by something, their display name where there is one and their
                # id otherwise.
                "COALESCE(a.name, p.attested_by::text), p.source_note "
                "FROM platform_model_prices p "
                "LEFT JOIN admin_users a ON a.id = p.attested_by "
                "WHERE p.effective_from <= :at "
                "ORDER BY p.model, p.effective_from DESC"
            ),
            {"at": at},
        )
    ).all()
    return {
        str(r[0]): AttestedModelPrice(
            model=str(r[0]),
            input_usd_per_mtok=r[1],
            output_usd_per_mtok=r[2],
            effective_from=r[3],
            attested_at=r[4],
            attested_by=str(r[5]),
            source_note=str(r[6]),
        )
        for r in rows
    }


async def _stored_credential_keys(session: AsyncSession) -> frozenset[str]:
    """Credential keys the founder has INSTALLED in the ops panel (a stored version).

    STORED (`version > 0`), not env-shadowed, and that is deliberate. The founder's stated
    workflow is that every vendor key goes in the ops panel — so a stored version is the
    signal that they have installed one — and counting a `.env`-declared key would make
    offerability diverge between a dev machine that carries one in `.env` and CI that does
    not (the exact local-vs-CI trap `_no_ambient_credentials` exists for, which cannot help
    here because `env_declares` reads the `.env` FILE). Azure's own key is env-injected from
    the secrets manager in production rather than stored here, but its leg is always usable
    anyway (see `installed_llm_legs`), so this stored-only rule never hides Azure.
    """
    return frozenset(r.key for r in await read_secrets(session) if r.version > 0)


async def installed_llm_legs(session: AsyncSession) -> frozenset[LlmProvider]:
    """Which declared legs this platform can put a call on today.

    ⚠ **`azure_openai` USED TO BE UNCONDITIONALLY PRESENT AND IS NOT ANY MORE.** The ground
    was that the leg is reachable without our key via the engine's own default client, so a
    deployment holding no Azure credential still offered every Azure-catalogue model. The
    founder read that screen on a deployment with no Azure resource, no Azure key and no
    Azure deployment and asked why those models were selectable. They should not have been:
    the engine's passthrough serves those identifiers from its OWN bundled OpenAI tier, not
    from Azure (`agents/llm_models.py`'s module docstring carries the vendor page and lines),
    so the panel was reporting an Azure leg nobody had installed. It is now read from
    `azure_credentials()` — the one definition of "the Azure leg is configured" in this tree,
    which sees the key wherever it came from: injected from the secrets manager in
    production, or stored here through the console.

    `openai` and `google` keys are NOT settings this API reads on a call path — they live in
    the ENGINE's own credential store — so for those two "installed" is what the founder
    stored in the panel (`_stored_credential_keys`). Returns `frozenset[LlmProvider]`, the
    shape the catalogue lane's `install_llm_credential_reader` consumes directly, and it
    reproduces `agents.llm_models.installed_llm_providers()`'s reader-less default exactly —
    the two must agree, because half a deployment reads one and half reads the other.
    """
    stored = await _stored_credential_keys(session)
    legs: set[LlmProvider] = set()
    if azure_credentials() is not None:
        legs.add("azure_openai")
    for provider, cred in PROVIDER_CREDENTIAL.items():
        if provider != "azure_openai" and cred in stored:
            legs.add(provider)
    return frozenset(legs)


@dataclass(frozen=True, slots=True)
class ModelOfferability:
    """One catalogue model, seen through the founder's offerability rule.

    `offerable` is `credential_installed AND price is BILLABLE`, and "billable" is the
    catalogue lane's own two-ground rule (`billing/rates.llm_price_is_billable`): a price is
    billable if an operator ATTESTED it OR the catalogue figure was READ FROM THE VENDOR
    (`reference_verified`). That second ground is why Azure is offerable with no attestation
    — D-410 read its price first-hand — while the OpenAI/Google legs, whose catalogue prices
    are REPORTED, become offerable only once the founder attests one. `price_attested` is
    kept as a SEPARATE field so the panel can show "attested" apart from "billable off the
    verified catalogue".

    It is NOT the whole story a client's picker tells: the catalogue lane's
    `available_models` composes this with `LlmModelSpec.selectable` (a model withheld on
    merit stays withheld however it is priced) and with a deployment's addressability.
    """

    model: str
    provider: LlmProvider
    credential_installed: bool
    price_attested: bool
    #: WITHHELD ON MERIT, and the reason, or `None` when this repository permits the model.
    #:
    #: THIS FIELD EXISTS BECAUSE ITS ABSENCE MISLED THE ONE PERSON IT IS FOR. The docstring
    #: above already said this dataclass is "NOT the whole story a client's picker tells"
    #: and named `LlmModelSpec.selectable` as the missing half — and the ops panel, having
    #: only these fields, told the founder that every unofferable model "becomes available
    #: to customers only once you confirm a price". For `gemini-3.*` and any model whose
    #: retirement stance is unread, that is false however the price is attested: a
    #: `selectable=False` model stays withheld, so the screen was inviting work that could
    #: not succeed and hiding the reason it could not — dead air on a phone call, a 10x
    #: cost tier, a vendor page nobody has read.
    #:
    #: Carried as the REASON rather than a boolean so the panel can say WHY without
    #: re-deriving it. `unofferable_reason` writes those sentences; this passes them on.
    withheld_reason: str | None
    #: The catalogue figure is a first-hand vendor reading (`LlmPrice.evidence.verified`) —
    #: billable with no attestation. True for Azure, False for the OpenAI/Google legs.
    reference_verified: bool

    @property
    def price_billable(self) -> bool:
        return self.price_attested or self.reference_verified

    @property
    def selectable(self) -> bool:
        """Does this repository permit the model at all, on merit?"""
        return self.withheld_reason is None

    @property
    def offerable(self) -> bool:
        """May a client pick it right now.

        ALL THREE GROUNDS, where this used to be two. `agents/llm_models.offerable_models`
        has always ANDed merit with the credential and the price; this property answered
        for the last two only, which was correct for its old callers and wrong for the one
        that reported it to a human as "available to customers".
        """
        return self.selectable and self.credential_installed and self.price_billable


async def model_offerability(
    session: AsyncSession, *, at: datetime
) -> dict[str, ModelOfferability]:
    """Every catalogue model's offerability at instant `at`.

    Over `LLM_MODELS` — the full catalogue, not the selectable subset — because the whole
    point is to show the founder which models are NOT yet offerable and what is missing
    (a credential, a price, or both). Sorted-key iteration is the caller's job; a dict is
    returned so a route can index by model.
    """
    prices = await attested_model_prices(session, at=at)
    legs = await installed_llm_legs(session)
    result: dict[str, ModelOfferability] = {}
    for model, spec in LLM_MODELS.items():
        result[model] = ModelOfferability(
            model=model,
            provider=spec.provider,
            credential_installed=spec.provider in legs,
            price_attested=model in prices,
            reference_verified=spec.price.evidence.verified,
            # `withheld_reason` from the catalogue, NOT re-derived here: those sentences
            # cite their own primary sources (a vendor enum with no zero, an engine branch
            # that yields nothing) and belong with the decision, not with the screen.
            # STRAIGHT OFF THE SPEC. `agents/llm_models.unofferable_reason` would also
            # answer, but it ANDs merit with the credential and the price, so a model
            # withheld on merit AND missing a key would report only the key — which is
            # the half a price screen can act on and the half that is not true.
            withheld_reason=spec.withdrawn_reason if not spec.selectable else None,
        )
    return result


async def offerable_models(session: AsyncSession, *, at: datetime) -> frozenset[str]:
    """The catalogue models whose credential is installed AND whose price is billable at
    `at`. The set half of `model_offerability`, for a caller that only needs membership."""
    return frozenset(
        model for model, o in (await model_offerability(session, at=at)).items() if o.offerable
    )


@dataclass(frozen=True, slots=True)
class DashboardDataUseAttestation:
    """What an operator attested about ONE provider's data-use terms, with its provenance.

    Frozen and provenance-carrying for `AttestedModelPrice`'s reasons: an attestation that
    reached a caller must not be mutable underneath it, and the next reader must inherit the
    evidence (`vendor_account_ref`, `source_note`, `attested_by`) rather than the conclusion.

    `permits_dashboard` is the AND of the two settings that can each defeat the paid tier —
    see `ops/models.PlatformDashboardDataUse` for what each one is and what neither of them
    buys. It is a property rather than a stored column so that the rule lives in one place
    and an old row can never disagree with today's rule about its own two booleans.
    """

    provider: LlmProvider
    vendor_account_ref: str
    paid_tier_confirmed: bool
    no_training_opt_in_confirmed: bool
    attested_at: datetime
    #: The operator, by display name where there is one and by id otherwise — never empty.
    attested_by: str
    source_note: str

    @property
    def permits_dashboard(self) -> bool:
        """May the dashboard assist run on this provider on the strength of this row?"""
        return self.paid_tier_confirmed and self.no_training_opt_in_confirmed


async def dashboard_data_use_attestations(
    session: AsyncSession,
) -> dict[LlmProvider, DashboardDataUseAttestation]:
    """The LATEST attestation for each provider, keyed by provider.

    Latest rather than effective-dated, and the difference from `attested_model_prices` is
    deliberate: a price is a fact about a PERIOD (a re-rendered invoice needs the figure that
    was live in its month), while a data-use term is a fact about NOW (may this content go to
    this vendor today). The history is kept because "what did we believe when" is the audit
    question, and it is read by the console, not by the gate.

    ONE ROUND TRIP: `DISTINCT ON (provider) … ORDER BY provider, attested_at DESC` over
    `ix_platform_dashboard_data_use_provider`, the same shape the price reader uses.

    A row naming a provider this build no longer declares is SKIPPED rather than raising: the
    table deliberately stores provider as text so history survives a leg being withdrawn, and
    a withdrawn leg's stale attestation must not blank every other provider's.
    """
    rows = (
        await session.execute(
            text(
                "SELECT DISTINCT ON (d.provider) d.provider, d.vendor_account_ref, "
                "d.paid_tier_confirmed, d.no_training_opt_in_confirmed, d.attested_at, "
                # COALESCE to the id text, never NULL — `admin_users.name` is nullable and an
                # unattributed attestation is not an attestation (`attested_by`'s comment on
                # the price reader gives the argument in full).
                "COALESCE(a.name, d.attested_by::text), d.source_note "
                "FROM platform_dashboard_data_use d "
                "LEFT JOIN admin_users a ON a.id = d.attested_by "
                "ORDER BY d.provider, d.attested_at DESC"
            )
        )
    ).all()
    declared = frozenset(get_args(LlmProvider))
    result: dict[LlmProvider, DashboardDataUseAttestation] = {}
    for r in rows:
        provider = str(r[0])
        if provider not in declared:
            continue
        result[cast("LlmProvider", provider)] = DashboardDataUseAttestation(
            provider=cast("LlmProvider", provider),
            vendor_account_ref=str(r[1]),
            paid_tier_confirmed=bool(r[2]),
            no_training_opt_in_confirmed=bool(r[3]),
            attested_at=r[4],
            attested_by=str(r[5]),
            source_note=str(r[6]),
        )
    return result


async def dashboard_permitted_providers(session: AsyncSession) -> frozenset[LlmProvider]:
    """The legs whose LATEST attestation permits the dashboard assist.

    The shape `agents/llm_models.install_dashboard_data_use_reader` consumes. An absent
    provider means NOBODY HAS ATTESTED, which the gate reports as an absent attestation —
    never as an operator having said no. The two are different states and only one is a
    finding (`dashboard_data_use_attested`'s docstring).
    """
    attested = await dashboard_data_use_attestations(session)
    return frozenset(p for p, a in attested.items() if a.permits_dashboard)


def _require_declared_provider(provider: str) -> LlmProvider:
    if provider not in get_args(LlmProvider):
        raise ProblemError(
            kind="not_found",
            code="dashboard_data_use_unknown_provider",
            title="No such AI provider",
            detail=f"{provider!r} isn't one of Calevate's declared LLM legs.",
            remediation=(
                "The declared legs are "
                + ", ".join(sorted(get_args(LlmProvider)))
                + ". Adding one is a code change, not something enterable here."
            ),
        )
    return cast("LlmProvider", provider)


async def attest_dashboard_data_use(
    session: AsyncSession,
    *,
    provider: str,
    vendor_account_ref: str,
    paid_tier_confirmed: bool,
    no_training_opt_in_confirmed: bool,
    attested_at: datetime,
    source_note: str,
    actor_id: object,
) -> DashboardDataUseAttestation:
    """Record ONE operator attestation as a NEW dated row. Never an UPDATE.

    The caller MUST have step-up confirmed and MUST write the audit row on this same session
    — `attest_price`'s contract exactly, because this is the same class of act: a person
    putting their name to a fact about the outside world that the platform will then rely on.

    **A "NO" IS A VALID AND USEFUL ATTESTATION AND IS NOT REFUSED.** Recording that an
    operator LOOKED and found the project on the unpaid tier is worth more than an absent
    row: the gate reports "nobody has attested" for the second and can report a checked
    negative for the first. So the two booleans are stored as given; only their AND decides
    eligibility.

    Refuses an undeclared provider (the leg vocabulary is closed), a blank project reference
    or evidence note (the database CHECK is the backstop; this is the sentence an operator can
    act on), and a duplicate `(provider, attested_at)` — a correction is a DISTINCT instant,
    so colliding on one means re-attesting the same instant, the one write this append-only
    table cannot express.
    """
    declared = _require_declared_provider(provider)
    account_ref = vendor_account_ref.strip()
    note = source_note.strip()
    if not account_ref or not note:
        raise ProblemError(
            kind="validation",
            code="dashboard_data_use_evidence_missing",
            title="An attestation needs the account it is about and where you looked",
            detail=(
                "Both the vendor project/account reference and the evidence note are required."
            ),
            remediation=(
                "Name the vendor project the platform's key for this provider belongs to "
                "(for Google, the Cloud project shown on the AI Studio Projects page), and "
                "say where you read the tier. Without the project reference nobody can ever "
                "re-check this claim — they can only re-make it."
            ),
        )
    existing = (
        await session.execute(
            text(
                "SELECT 1 FROM platform_dashboard_data_use "
                "WHERE provider = :p AND attested_at = :at"
            ),
            {"p": declared, "at": attested_at},
        )
    ).first()
    if existing is not None:
        raise ProblemError(
            kind="conflict",
            code="dashboard_data_use_duplicate_instant",
            title="An attestation already exists for this provider at this instant",
            detail=(
                f"{declared!r} already has an attestation at {attested_at.isoformat()}. A "
                "correction is a NEW instant, never an edit of an existing one."
            ),
            remediation=(
                "Attest again with a later instant (the default is now). The history is "
                "append-only by design — it is the record of what was believed, and when."
            ),
        )
    await session.execute(
        text(
            "INSERT INTO platform_dashboard_data_use "
            "(provider, attested_at, attested_by, vendor_account_ref, paid_tier_confirmed, "
            "no_training_opt_in_confirmed, source_note) "
            "VALUES (:p, :at, :by, :ref, :paid, :noopt, :note)"
        ),
        {
            "p": declared,
            "at": attested_at,
            "by": actor_id,
            "ref": account_ref,
            "paid": paid_tier_confirmed,
            "noopt": no_training_opt_in_confirmed,
            "note": note,
        },
    )
    return DashboardDataUseAttestation(
        provider=declared,
        vendor_account_ref=account_ref,
        paid_tier_confirmed=paid_tier_confirmed,
        no_training_opt_in_confirmed=no_training_opt_in_confirmed,
        attested_at=attested_at,
        attested_by=str(actor_id),
        source_note=note,
    )


def _require_known_model(model: str) -> None:
    if model not in LLM_MODELS:
        raise ProblemError(
            kind="not_found",
            code="model_price_unknown_model",
            title="No such model",
            detail=f"{model!r} isn't a model in Calevate's catalogue.",
            remediation=(
                "The model-prices list shows every model, its provider and whether it "
                "still needs a price. Adding a new model is a code change, not something "
                "that can be entered here as a price on its own."
            ),
        )


async def attest_price(
    session: AsyncSession,
    *,
    model: str,
    input_usd_per_mtok: Decimal,
    output_usd_per_mtok: Decimal,
    effective_from: datetime,
    source_note: str,
    actor_id: object,
) -> AttestedModelPrice:
    """Record one operator-attested price as a NEW effective-dated row. Never an UPDATE.

    The caller MUST have step-up confirmed and MUST write the audit row on this same
    session. Refuses an unknown model (the catalogue is closed), a negative price (the
    database CHECK is the backstop; this is the message an operator can act on) and a
    duplicate `(model, effective_from)` — a correction is a DISTINCT instant, so colliding
    on one means the operator is re-attesting the same instant, which is the one write this
    append-only table cannot express and must refuse with a sentence rather than a 500 on a
    primary-key violation.

    `effective_from` is the caller's fact: `now()` for "this is the price from here on",
    an earlier instant to correct the record for a period already elapsed. It is validated
    (timezone-aware) at the API boundary, not here, because the type is enforced there.
    """
    _require_known_model(model)
    if input_usd_per_mtok <= 0 or output_usd_per_mtok <= 0:
        raise ProblemError(
            kind="validation",
            code="model_price_not_positive",
            title="A price must be greater than zero",
            detail="Both figures are USD per million tokens and must be strictly positive.",
            remediation=(
                "Enter the vendor's list price. A zero is refused because it bills every "
                "minute on this model at nothing while looking like a working leg "
                "(billing/rates.LlmPriceAttestation refuses it for the same reason)."
            ),
        )
    # The PK collision, turned into a sentence. `pg_advisory_xact_lock` on the model is not
    # needed — the PK is `(model, effective_from)` and two writers colliding on it is
    # exactly the state we want to refuse — but reading first lets the message name the
    # existing row rather than surfacing a raw IntegrityError as a 500.
    existing = (
        await session.execute(
            text("SELECT 1 FROM platform_model_prices WHERE model = :m AND effective_from = :ef"),
            {"m": model, "ef": effective_from},
        )
    ).first()
    if existing is not None:
        raise ProblemError(
            kind="conflict",
            code="model_price_duplicate_instant",
            title="A price already exists for this model at this instant",
            detail=(
                f"{model!r} already has an attestation effective from "
                f"{effective_from.isoformat()}. A correction is a NEW effective instant, "
                "never an edit of an existing one."
            ),
            remediation=(
                "To change the price from here on, attest it with a later effective_from "
                "(the default is now). The history is append-only by design."
            ),
        )
    row = (
        await session.execute(
            text(
                "INSERT INTO platform_model_prices "
                "(model, effective_from, input_usd_per_mtok, output_usd_per_mtok, "
                "attested_by, source_note) "
                "VALUES (:m, :ef, :in, :out, :by, :note) "
                "RETURNING attested_at"
            ),
            {
                "m": model,
                "ef": effective_from,
                "in": input_usd_per_mtok,
                "out": output_usd_per_mtok,
                "by": actor_id,
                "note": source_note,
            },
        )
    ).one()
    return AttestedModelPrice(
        model=model,
        input_usd_per_mtok=input_usd_per_mtok,
        output_usd_per_mtok=output_usd_per_mtok,
        effective_from=effective_from,
        attested_at=row[0],
        attested_by=str(actor_id),
        source_note=source_note,
    )


def reference_price(model: str) -> tuple[Decimal, Decimal, bool]:
    """The catalogue's own price for `model`, and whether its evidence is verified.

    This is what the console pre-fills the attestation form with — GREYED and labelled
    "unverified — confirm against your vendor invoice" when `verified` is False — never as
    the authoritative value. For Azure's two models the catalogue price IS verified (D-410's
    own reading), so the console can say so; for the OpenAI/Google legs it is REPORTED, which
    is precisely why an attestation is needed. Raises for an unknown model, like every other
    reader here."""
    _require_known_model(model)
    price = LLM_MODELS[model].price
    return price.input_usd_per_mtok, price.output_usd_per_mtok, price.evidence.verified


__all__ = [
    "PROVIDER_CREDENTIAL",
    "AttestedModelPrice",
    "ModelOfferability",
    "attest_price",
    "attested_model_prices",
    "installed_llm_legs",
    "model_offerability",
    "offerable_models",
    "reference_price",
]
