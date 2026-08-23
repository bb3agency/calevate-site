"""Operator-attested model prices — the surface the founder types a vendor price into (§5).

    GET  /v1/ops/model-prices          every catalogue model: provider, reference price,
                                        attested price (or "needs a price"), offerability
    POST /v1/ops/model-prices/{model}  attest a price; step-up `attest_model_price:<model>`

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
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Path, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import global_db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.core.stepup import StepUpGate
from apps.api.ops.model_pricing import (
    AttestedModelPrice,
    ModelOfferability,
    attest_price,
    attested_model_prices,
    model_offerability,
    reference_price,
)
from apps.api.ops.pricing_snapshot import refresh_pricing_snapshot

router = APIRouter(prefix="/v1/ops/model-prices", tags=["ops"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]
PriceOperator = Annotated[Principal, Depends(requires("platform:config", realm="admin"))]

# A model identifier on the wire. Bounded because it is interpolated into a step-up string
# and an audit summary and is attacker-controlled on any surface — the character class every
# `LLM_MODELS` key uses (lower-case letters, digits, dots and hyphens). NOT an allow-list of
# known models: the service refuses an unknown one by name, and a second copy of the
# catalogue here is the drift this slice avoids.
ModelId = Annotated[str, Path(max_length=64, pattern=r"^[a-z0-9][a-z0-9.\-]*$")]

# The widest a per-million-token USD price can be and still fit NUMERIC(12,6): six integer
# digits. A price at or above a million dollars per million tokens is not a typo this API
# should try to store.
_MAX_USD_PER_MTOK = Decimal("1000000")


def attest_confirmation(model: str) -> str:
    """The step-up string for attesting ONE model's price.

    A named function with a test pinning the literal, like `config_confirmation` and
    `secret_confirmation`: it is an ops procedure a runbook prints. Bound to the MODEL, so a
    header captured for pricing gpt-4o-mini cannot be replayed to reprice gpt-5.6-luna.
    """
    return f"attest_model_price:{model}"


def _money(field_name: str, raw: str) -> Decimal:
    """A money string to a `Decimal`, or a boundary refusal. Never `float(...)`.

    Hard rule 7 does not stop at the database: the value arrives as a STRING and becomes a
    `Decimal` directly, so it never passes through a binary float. A non-numeric value, a
    NaN/Inf, a negative, an out-of-range or an over-precise one is refused HERE with the
    field named, rather than surfacing as a NUMERIC overflow from Postgres.
    """
    try:
        value = Decimal(raw.strip())
    except (InvalidOperation, ValueError):
        raise ValueError(
            f"{field_name} must be a decimal number of USD per million tokens"
        ) from None
    if not value.is_finite():
        raise ValueError(f"{field_name} must be a finite number")
    if value <= 0:
        # Not "> 0 for tidiness": a zero (or negative) attested price bills every minute on
        # the model at nothing while looking like a working leg — `billing/rates
        # .LlmPriceAttestation` refuses it for the same reason, and the two must agree or an
        # accepted zero would crash the snapshot that feeds billing.
        raise ValueError(f"{field_name} must be greater than zero (a zero bills nothing)")
    if value >= _MAX_USD_PER_MTOK:
        raise ValueError(f"{field_name} is implausibly large for a per-Mtok price")
    # `exponent` is `int` for a finite Decimal (guarded above) but typed as
    # `int | Literal['n','N','F']` for the NaN/Inf cases — `isinstance` narrows it for the
    # type checker and is a no-op at runtime here.
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and -exponent > 6:
        raise ValueError(
            f"{field_name} has more than six decimal places, which this store cannot hold"
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
    #: `credential_installed AND price_attested`. NOT the whole client-picker story — the
    #: catalogue lane composes this with `selectable` and deployment addressability.
    offerable: bool
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


class ModelPricesOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prices: list[ModelPriceOut]
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


@router.get(
    "",
    response_model=ModelPricesOut,
    openapi_extra=permission_meta("platform:config"),
    summary="Every model's provider, reference price, attested price and offerability",
    description=(
        "Lists every model in the catalogue with its declared leg, the catalogue's own "
        "(possibly unverified) reference price, the operator-attested price if one exists, "
        "and whether the model is offerable yet — which needs BOTH its provider credential "
        "installed AND a price attested. A model with no attested price is shown as needing "
        "one; the reference price is a pre-fill to confirm against a vendor invoice, never "
        "the authoritative value."
    ),
)
async def list_model_prices(session: GlobalSession, _: PriceOperator) -> ModelPricesOut:
    at = datetime.now(UTC)
    return ModelPricesOut(prices=await _rows(session, at=at), as_of=at.isoformat())


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
            remediation='Send USD per million tokens as a decimal string, e.g. "0.15".',
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


__all__ = ["attest_confirmation", "router"]
