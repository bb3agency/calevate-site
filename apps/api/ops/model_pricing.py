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
from typing import Final, cast, get_args

from calevate_shared.engine import LLM_MODELS, LlmProvider
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing import rates
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
    here because `env_declares` reads the `.env` FILE).

    ⚠ **THIS USED TO END "Azure's own key is env-injected … but its leg is always usable
    anyway (see `installed_llm_legs`), so this stored-only rule never hides Azure." THAT
    RULE IS GONE AND THE SENTENCE IS FALSE.** `installed_llm_legs` below admits
    `azure_openai` only when `azure_credentials()` answers with all three of resource, key
    and deployment. The stored-only rule genuinely does not hide Azure — but the reason is
    that Azure's leg is decided by `azure_credentials()` rather than by this set at all,
    NOT that the leg is always usable. Keeping the old wording would tell the next reader
    that an Azure model can never be un-offered, which is the defect the credential check
    was added to fix.
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


# --- the TTS leg: the same act, one vendor further down the call (D-547) ----------
#
# WHY IT LIVES HERE. A price an operator reads off their own invoice is one kind of act
# whatever the vendor sells, and this module is where that act is performed, audited and
# read back. The TTS attestation is the LLM attestation with two words changed — a
# PROVIDER instead of a model, rupees per 1,000 CHARACTERS instead of dollars per million
# TOKENS — and it gates offerability by the identical rule.
#
# WHY IT IS NOT IN `billing/rates.py` BESIDE `LlmPriceAttestation`: plan §3.5 put it there,
# and it is the wrong side of the seam. `rates.py` is arithmetic over figures somebody else
# supplies; the SUPPLYING is an ops concern, which is why the LLM twin's storage, its
# effective-dated reader and its offerability rule are all in this file already. Splitting
# the pair across two modules would put one attestation in each.


#: The voice tiers that CAN carry an attested TTS price. The same vocabulary as
#: `agents/voices.VoiceProvider` and `billing/lots.VoiceTier`, spelled here as the DB's
#: `platform_tts_prices.provider` column values; `tests/tts_price_attestation_test.py`
#: holds the three in step so a fourth vendor cannot be priced under a name the pipeline
#: does not stamp.
TTS_PROVIDERS: Final[tuple[str, ...]] = ("sarvam", "cartesia")


@dataclass(frozen=True, slots=True)
class TtsPriceAttestation:
    """What an operator read off their own TTS invoice, for ONE voice provider.

    **RUPEES PER 1,000 CHARACTERS, and the unit is not a detail.** A TTS vendor on a
    monthly plan sells an ALLOTMENT, not a per-call charge: the price of a character is
    the committed spend divided by the characters it buys, and only a human holding the
    invoice can do that division. That is also the whole reason this record exists rather
    than a constant — `engine.CostBreakdown.tts_inr` reports ₹0 for a BYOK leg (plan
    ADDENDUM 3 §3.5), so without an attested figure a Cartesia minute would meter as free.

    ⚠ **WHICH REGIME AN ATTESTED FIGURE BELONGS TO IS THE OPERATOR'S TO STATE.** Characters
    past the allotment cost the vendor's OVERAGE rate, which is no longer unknown — D-556
    (9 Sep 2026) closed it from direct correspondence at $65 / $45 / $38 per 1,000,000
    credits on Pro / Startup / Scale, and `rates.CARTESIA_MARGINAL_TTS_INR_PER_10K_CHARS`
    is the Pro figure the form pre-fills. But an operator reading an invoice may be
    attesting an INCLUDED-allotment average instead, and the two are different numbers for
    the same month; `source_note` names the plan and the period so a reader can tell which.
    ⚠ This paragraph read "**UNKNOWN** ... No overage number is invented" until D-556.

    Every field but the price is PROVENANCE, exactly as on `LlmPriceAttestation`: a figure
    in a table is indistinguishable from one somebody guessed, and `attested_at` is what
    makes an attestation stale rather than merely old.
    """

    provider: str
    inr_per_1k_chars: Decimal
    effective_from: datetime
    attested_at: datetime
    #: The operator, by id — never empty, because the billing seam refuses an
    #: unattributed attestation (D-31/D-32).
    attested_by: str
    source_note: str

    def inr_for_chars(self, characters: Decimal) -> Decimal:
        """What `characters` cost at this rate. The ONE multiplication, so the pipeline
        and the margin panel cannot each carry a divisor."""
        return characters * self.inr_per_1k_chars / Decimal("1000")


def _require_tts_provider(provider: str) -> str:
    if provider not in TTS_PROVIDERS:
        raise ProblemError(
            kind="not_found",
            code="tts_price_unknown_provider",
            title="No such voice provider",
            detail=f"{provider!r} isn't a voice provider Calevate synthesises with.",
            remediation=(
                "Prices are attested per voice provider. Adding a provider is a code "
                "change (the voice catalogue and the engine adapter both have to know "
                "it), not something that can be entered here as a price on its own."
            ),
        )
    return provider


async def attested_tts_prices(
    session: AsyncSession, *, at: datetime
) -> dict[str, TtsPriceAttestation]:
    """Every provider's TTS price effective at instant `at`, keyed by provider.

    `DISTINCT ON` with the greatest `effective_from <= at`, exactly as
    `attested_model_prices` resolves an LLM price and for the same reason: a month
    re-rendered next year must resolve the figure its minutes were metered at, not
    today's. A provider with no attestation on or before `at` is ABSENT — the caller
    decides what that means, and every caller in this tree decides the same thing
    (`tts_price_is_billable` says it in one place).
    """
    if at.tzinfo is None:
        raise ValueError("`at` must be timezone-aware — a naive instant has no month")
    rows = (
        await session.execute(
            text(
                "SELECT DISTINCT ON (provider) provider, inr_per_1k_chars, effective_from, "
                "attested_at, attested_by, source_note FROM platform_tts_prices "
                "WHERE effective_from <= :at ORDER BY provider, effective_from DESC"
            ),
            {"at": at},
        )
    ).all()
    return {
        str(row[0]): TtsPriceAttestation(
            provider=str(row[0]),
            # `Decimal(str(...))`, never `Decimal(...)`: the convention every NUMERIC read
            # in this tree keeps, so the day a driver hands back a float the price does not
            # inherit the binary error.
            inr_per_1k_chars=Decimal(str(row[1])),
            effective_from=row[2],
            attested_at=row[3],
            attested_by=str(row[4]),
            source_note=str(row[5]),
        )
        for row in rows
    }


async def tts_price_is_billable(session: AsyncSession, *, provider: str, at: datetime) -> bool:
    """May a call on this voice provider be METERED at a cost? THE one door.

    Hard rule 7's structural form, one vendor further down than
    `billing/rates.llm_inr_per_ktok`: a catalogue figure has NO path to `unit_cost_paid`,
    and the only figure that does is one a human read off an invoice. `False` here is what
    makes `agents/voice_offer.offerable_voices` refuse the tier by name rather than
    offering a voice whose minutes would meter as free — the same rule
    `offerable_models` applies to a language model.

    Sarvam answers True without an attestation and that is not an exemption: the ENGINE
    bills us for the Sarvam synthesizer leg and reports what it charged, so that leg has a
    measured cost on every row (`CostBreakdown.tts_inr`) and no attestation to make. It is
    BYOK legs — where the engine charges nothing and the vendor bills a monthly plan — that
    have no cost at all without one. Whether the engine's own Sarvam figure is right is a
    different question and a different gate (OPERATIONS §2 gate 7), unchanged here.
    """
    if _require_tts_provider(provider) == "sarvam":
        return True
    return provider in await attested_tts_prices(session, at=at)


def reference_tts_price(provider: str) -> Decimal:
    """The tree's OWN per-1,000-character figure for `provider` — the form's pre-fill.

    `reference_price`'s job for a voice, and it carries `reference_price`'s warning twice
    over: this is NOT authoritative and no caller may bill from it. It is rendered GREYED
    beside the form, labelled "confirm against your vendor invoice", because an operator
    typing a price from a paper invoice is helped by seeing what this platform currently
    believes and is not helped by having it entered for them.

    NEITHER FIGURE IS A PRICE SOMEBODY READ OFF AN INVOICE, which is why there is no
    `verified` flag to return: Sarvam's is the published list rate for Bulbul v3
    (`rates.TTS_INR_PER_10K_CHARS`, evidence class VENDOR-PUBLISHED) and Cartesia's is the
    vendor's OVERAGE rate on the dearest plan we can be on, ₹57.20/10,000 characters
    (`rates.CARTESIA_MARGINAL_TTS_INR_PER_10K_CHARS`, VENDOR-PUBLISHED — Tinmaz
    correspondence, 9 Sep 2026). ⚠ **IT USED TO BE THE STARTUP FEE DIVIDED BY THE
    CHARACTERS IT BUYS** (₹34.496/10,000), which is true only when the whole allotment is
    spoken and was silent about the overage rate, then UNKNOWN. A per-character AVERAGE is
    true at exactly one volume; a MARGINAL rate is true at every volume past the allotment,
    and it is the one an operator can sanity-check a line on an invoice against. That is
    still not a price anybody read off ours, which is why hard rule 7 keeps both out of
    `unit_cost_paid` and why the attestation exists.

    Raises for an unknown provider, like every other reader here.
    """
    _require_tts_provider(provider)
    per_10k = (
        rates.TTS_INR_PER_10K_CHARS
        if provider == "sarvam"
        else rates.CARTESIA_MARGINAL_TTS_INR_PER_10K_CHARS
    )
    return per_10k / Decimal("10")


async def attest_tts_price(
    session: AsyncSession,
    *,
    provider: str,
    inr_per_1k_chars: Decimal,
    effective_from: datetime,
    source_note: str,
    actor_id: object,
) -> TtsPriceAttestation:
    """Record one operator-attested TTS price as a NEW effective-dated row. Never an UPDATE.

    `attest_price`'s contract, verbatim, because it is the same act: the caller MUST have
    step-up confirmed and MUST write the audit row on this same session; an unknown
    provider, a non-positive figure and a duplicate `(provider, effective_from)` are each
    refused with a sentence an operator can act on rather than a 500 on a constraint.
    """
    _require_tts_provider(provider)
    if inr_per_1k_chars <= 0:
        raise ProblemError(
            kind="validation",
            code="tts_price_not_positive",
            title="A price must be greater than zero",
            detail="The figure is rupees per 1,000 characters and must be strictly positive.",
            remediation=(
                "Enter the plan's marginal rate — the committed spend divided by the "
                "characters it buys. A zero is refused because it meters every character "
                "on this voice at nothing while looking like a working leg."
            ),
        )
    existing = (
        await session.execute(
            text("SELECT 1 FROM platform_tts_prices WHERE provider = :p AND effective_from = :ef"),
            {"p": provider, "ef": effective_from},
        )
    ).first()
    if existing is not None:
        raise ProblemError(
            kind="conflict",
            code="tts_price_duplicate_instant",
            title="A price already exists for this voice at this instant",
            detail=(
                f"{provider!r} already has an attestation effective from "
                f"{effective_from.isoformat()}. A correction is a NEW effective instant, "
                "never an edit of an existing one."
            ),
            remediation=(
                "To change the price from here on, attest it again with a later effective "
                "date (the default is now). The history is append-only by design."
            ),
        )
    row = (
        await session.execute(
            text(
                "INSERT INTO platform_tts_prices "
                "(provider, effective_from, inr_per_1k_chars, attested_by, source_note) "
                "VALUES (:p, :ef, :rate, :by, :note) RETURNING attested_at"
            ),
            {
                "p": provider,
                "ef": effective_from,
                "rate": inr_per_1k_chars,
                "by": actor_id,
                "note": source_note,
            },
        )
    ).one()
    return TtsPriceAttestation(
        provider=provider,
        inr_per_1k_chars=inr_per_1k_chars,
        effective_from=effective_from,
        attested_at=row[0],
        attested_by=str(actor_id),
        source_note=source_note,
    )


# --- the TTS PLAN FEE: what the vendor BILLED, beside what our meter attributed -------
#
# WHY A SECOND ATTESTATION AND NOT A SECOND COLUMN ON THE FIRST. `TtsPriceAttestation`
# above answers "what does one CHARACTER cost" — the figure a usage row multiplies, and a
# RATE that applies from an instant until a later attestation supersedes it, deliberately
# not per month. A plan FEE is the opposite shape: a committed monthly spend that belongs
# to exactly one month and says nothing about any other, paid whether or not the allotment
# is spoken. Folding them together would give one table two keys and a nullable figure in
# each row. It is the SAME ACT — an operator reads their own invoice and puts their name to
# a number — so it keeps the same provenance columns, the same append-only rule and the
# same refusals; only the subject changes.
#
# ⚠ IT IS NOT AN INPUT TO `unit_cost_paid` AND MUST NEVER BECOME ONE. A call's cost is the
# attested PER-CHARACTER rate times the characters it spoke; dividing this fee by a month's
# characters after the fact would re-price a month whose ledger rows are already written.
# It is PUBLISHED BESIDE the metered total (`billing/spend_routes.py`), never folded in.


#: The voice providers whose synthesizer leg this platform pays for as a MONTHLY PLAN, and
#: whose attributed cost therefore lands on `usage_events.unit_type = 'tts_kchars'`.
#:
#: THE UNIT TYPE IS THE PROVIDER DISCRIMINATOR, and that is a fact about the writer rather
#: than a convention: `workers/pipeline.py::_tts_cost_row` writes `tts_kchars` on the BYOK
#: branch only — a Sarvam call's synthesizer cost is the ENGINE's own reported leg figure
#: on a `tts_chars` row at `qty = 1`, which is a whole-leg charge and carries no character
#: count at all. So a `tts_kchars` sum IS this set's attributed cost, and a provider
#: outside the set has no character count of ours to compare an invoice against.
#:
#: `tests/tts_plan_fee_test.py` pins it inside `TTS_PROVIDERS` and pins Sarvam OUT of it, so
#: a third vendor arriving on a monthly plan is one edit here rather than a silent zero on
#: the spend board.
PLAN_BILLED_TTS_PROVIDERS: Final[frozenset[str]] = frozenset({"cartesia"})


@dataclass(frozen=True, slots=True)
class TtsPlanFeeAttestation:
    """What a voice vendor BILLED US for one IST month, as the invoice states it.

    RUPEES FOR THE WHOLE MONTH, not a rate — there is nothing to divide here, and the
    division by the allotment is `TtsPriceAttestation`'s figure. Frozen and provenance-
    carrying for that class's reasons: an attestation that reached a caller must not be
    mutable underneath it, and `source_note` is what makes the next reader inherit the
    evidence (which plan, which invoice) rather than the conclusion.

    ⚠ **UNKNOWN: whether the vendor's own character count agrees with ours** (OPERATIONS §2
    gate 51). `usage_events.qty` on a `tts_kchars` row is counted from OUR transcript and
    from nothing the vendor says, so what this row records and what our meter attributed
    are two independent measurements. The spend board publishes both and reconciles
    neither; nothing here closes that gate.

    ⚠ **UNKNOWN: the vendor's OVERAGE rate past the allotment** (plan ADDENDUM 1, unknown
    #3). This figure is what the invoice SAYS, so a month that ran into overage records the
    larger number and needs no separate rate — but the per-character attestation beside it
    still prices only characters INSIDE the allotment, and no overage number is invented in
    either place.
    """

    provider: str
    #: The IST billing month the invoice covers, `YYYY-MM` — `billing/plans
    #: .ist_billing_month`'s own spelling, which is what the spend board groups by.
    month: str
    plan_inr: Decimal
    effective_from: datetime
    attested_at: datetime
    #: The operator, by id — never empty, because the billing seam refuses an
    #: unattributed attestation (D-31/D-32).
    attested_by: str
    source_note: str

    def unused_inr(self, attributed_inr: Decimal) -> Decimal:
        """The allotment nobody spoke into: the fee, less what our meter attributed.

        THE ONE SUBTRACTION, on the SERVER (D-458). A browser subtracting two decimal
        strings is float arithmetic on money, and its answer would be a third figure
        disagreeing with both. It may be NEGATIVE, and that is a real and useful state
        rather than an error to clamp: it means the month attributed more than the plan
        charged, which is what running into an overage looks like from our side of the
        meter. The signed difference is the honest report either way: the attested
        per-character price may have been struck inside the allotment, so the excess is a
        real fact about the month even now that the vendor's overage rate is known (D-556).
        """
        return self.plan_inr - attributed_inr


def _require_plan_billed_provider(provider: str) -> str:
    """A provider that is billed as a monthly plan, or the sentence saying why not.

    Refused rather than stored, because a stored fee for a provider outside
    `PLAN_BILLED_TTS_PROVIDERS` would render a spend-board row whose `attributed_inr` is
    structurally ZERO — no `tts_kchars` row is ever written for that leg — and whose
    unused-allotment figure would therefore be the whole fee. That is a wrong number in the
    flattering direction ("we are wasting the entire plan"), arrived at from a true
    attestation, which is the worst kind.
    """
    _require_tts_provider(provider)
    if provider not in PLAN_BILLED_TTS_PROVIDERS:
        raise ProblemError(
            kind="validation",
            code="tts_plan_fee_provider_not_plan_billed",
            title="This voice vendor is not billed as a monthly plan",
            detail=(
                f"{provider!r} is metered from the engine's own reported synthesizer leg on "
                "every call, so there is no monthly invoice of ours to attest and no "
                "character count of ours to compare one against."
            ),
            remediation=(
                "Monthly plan fees are attested for "
                + ", ".join(sorted(PLAN_BILLED_TTS_PROVIDERS))
                + ". If this vendor has moved onto a plan, that is a code change — the "
                "metering has to write a per-character row for it first."
            ),
        )
    return provider


async def attested_tts_plan_fees(
    session: AsyncSession, *, month: str, at: datetime
) -> dict[str, TtsPlanFeeAttestation]:
    """Every provider's attested plan fee for ONE IST month, keyed by provider.

    `at` IS THE BELIEF INSTANT, NOT THE MONTH, and the difference from
    `attested_tts_prices` is the whole reason both exist. A price is resolved AT the month
    it priced, because a call's cost was struck inside it. A FEE arrives on an invoice
    AFTER the month has closed — often weeks after — so resolving it at the month's own
    last instant would make every correction, and usually the original attestation itself,
    invisible. So `month` selects the subject and `at` selects which attestation about that
    subject was live: `now()` for the live board, an earlier instant to reproduce what a
    board rendered on a past day.

    A provider with no attestation for `month` on or before `at` is ABSENT from the
    mapping, and every caller in this tree treats that the same way: the row is not
    rendered at all. ₹0 would read as "the vendor billed us nothing", which is the one
    misreading of a missing invoice that flatters us.

    ONE ROUND TRIP: `DISTINCT ON (provider) … ORDER BY provider, effective_from DESC` over
    `ix_platform_tts_plan_fees_provider_month`, the shape every reader in this module uses.
    """
    if at.tzinfo is None:
        raise ValueError("`at` must be timezone-aware — a naive instant has no month")
    rows = (
        await session.execute(
            text(
                "SELECT DISTINCT ON (provider) provider, month, plan_inr, effective_from, "
                "attested_at, attested_by, source_note FROM platform_tts_plan_fees "
                "WHERE month = :month AND effective_from <= :at "
                "ORDER BY provider, effective_from DESC"
            ),
            {"month": month, "at": at},
        )
    ).all()
    return {
        str(row[0]): TtsPlanFeeAttestation(
            provider=str(row[0]),
            month=str(row[1]),
            # `Decimal(str(...))`, never `Decimal(...)`: the convention every NUMERIC read
            # in this tree keeps, so the day a driver hands back a float the fee does not
            # inherit the binary error.
            plan_inr=Decimal(str(row[2])),
            effective_from=row[3],
            attested_at=row[4],
            attested_by=str(row[5]),
            source_note=str(row[6]),
        )
        for row in rows
    }


def reference_tts_plan_fee(provider: str) -> Decimal:
    """This tree's OWN monthly figure for `provider` — the form's pre-fill, nothing more.

    `reference_tts_price`'s job for a whole month, and it carries that function's warning
    unchanged: hard rule 7 gives a catalogue figure NO path to a cost we report as paid.

    ⚠ **THE PRE-FILL IS THE ENTRY PLAN'S FEE AND IT USED TO BE STARTUP'S ₹4,312.** The
    vendor states that the smallest paid path is **Pro at $5/month** (Tinmaz correspondence,
    9 Sep 2026), not the $49 Startup plan this tree assumed was the entry point — so ₹440 is
    what a first invoice most plausibly says, and pre-filling ₹4,312 would have had an
    operator confirming a figure an order of magnitude out. Which plan we are ACTUALLY on is
    a fact no code in this repository holds: it is on a card statement, which is exactly
    what the attestation captures. Rendered GREYED beside the form and labelled "confirm
    against your vendor invoice".

    **THE PRE-FILL CONVERTS AT THE FROZEN ₹88, NOT AT THE LIVE RATE, AND THAT IS DELIBERATE
    EVEN THOUGH THE COST FLOOR NOW DOES THE OPPOSITE** (founder, 9 Sep 2026). The floor is a
    number we reason about; this is a number an operator is about to overwrite from a card
    statement. A pre-fill that changed every five minutes would make two operators
    confirming the same invoice see two different greyed figures, which is a worse form of
    the same confusion. `rates.CARTESIA_EVIDENCE_USD_INR` is named at the call so the
    conversion is visible rather than defaulted.

    Raises for a provider that is not billed as a monthly plan, like the writer does.
    """
    _require_plan_billed_provider(provider)
    return rates.CARTESIA_PRO_PLAN.fee_inr(rates.CARTESIA_EVIDENCE_USD_INR)


async def attest_tts_plan_fee(
    session: AsyncSession,
    *,
    provider: str,
    month: str,
    plan_inr: Decimal,
    effective_from: datetime,
    source_note: str,
    actor_id: object,
) -> TtsPlanFeeAttestation:
    """Record one operator-attested monthly plan fee as a NEW dated row. Never an UPDATE.

    `attest_tts_price`'s contract, verbatim, because it is the same act: the caller MUST
    have step-up confirmed and MUST write the audit row on this same session; a provider
    that is not plan-billed, a non-positive figure and a duplicate
    `(provider, month, effective_from)` are each refused with a sentence an operator can
    act on rather than a 500 on a constraint.

    A CORRECTION IS A LATER ATTESTATION FOR THE SAME MONTH — a distinct `effective_from`,
    never an edit — so the history of what we believed we were billed, and when, survives
    the correction that superseded it.

    `month` is validated (shape) at the API boundary, where the type is enforced; the
    database CHECK is the backstop.
    """
    _require_plan_billed_provider(provider)
    if plan_inr <= 0:
        raise ProblemError(
            kind="validation",
            code="tts_plan_fee_not_positive",
            title="A plan fee must be greater than zero",
            detail="The figure is rupees for the whole month and must be strictly positive.",
            remediation=(
                "Enter the amount on the invoice. A zero is refused because it is "
                "indistinguishable on the spend board from the vendor having billed us "
                "nothing — and a month nobody has attested is shown as absent, precisely "
                "so those two states never look alike."
            ),
        )
    existing = (
        await session.execute(
            text(
                "SELECT 1 FROM platform_tts_plan_fees "
                "WHERE provider = :p AND month = :m AND effective_from = :ef"
            ),
            {"p": provider, "m": month, "ef": effective_from},
        )
    ).first()
    if existing is not None:
        raise ProblemError(
            kind="conflict",
            code="tts_plan_fee_duplicate_instant",
            title="A plan fee already exists for this vendor and month at this instant",
            detail=(
                f"{provider!r} already has an attestation for {month} effective from "
                f"{effective_from.isoformat()}. A correction is a NEW effective instant, "
                "never an edit of an existing one."
            ),
            remediation=(
                "To correct the figure, attest it again with a later effective date (the "
                "default is now). The history is append-only by design — it is the record "
                "of what we believed we were billed, and when."
            ),
        )
    row = (
        await session.execute(
            text(
                "INSERT INTO platform_tts_plan_fees "
                "(provider, month, effective_from, plan_inr, attested_by, source_note) "
                "VALUES (:p, :m, :ef, :fee, :by, :note) RETURNING attested_at"
            ),
            {
                "p": provider,
                "m": month,
                "ef": effective_from,
                "fee": plan_inr,
                "by": actor_id,
                "note": source_note,
            },
        )
    ).one()
    return TtsPlanFeeAttestation(
        provider=provider,
        month=month,
        plan_inr=plan_inr,
        effective_from=effective_from,
        attested_at=row[0],
        attested_by=str(actor_id),
        source_note=source_note,
    )


__all__ = [
    "PLAN_BILLED_TTS_PROVIDERS",
    "PROVIDER_CREDENTIAL",
    "TTS_PROVIDERS",
    "AttestedModelPrice",
    "ModelOfferability",
    "TtsPlanFeeAttestation",
    "TtsPriceAttestation",
    "attest_price",
    "attest_tts_plan_fee",
    "attest_tts_price",
    "attested_model_prices",
    "attested_tts_plan_fees",
    "attested_tts_prices",
    "installed_llm_legs",
    "model_offerability",
    "offerable_models",
    "reference_price",
    "reference_tts_plan_fee",
    "reference_tts_price",
    "tts_price_is_billable",
]
