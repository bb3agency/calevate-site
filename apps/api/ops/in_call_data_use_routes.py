"""The operator's attestation about an LLM provider's data-use terms for RAW CALLER SPEECH.

    GET  /v1/ops/in-call-data-use             each provider our own model can answer calls
                                               on: whether its latest attestation permits
                                               caller speech, and that attestation
    POST /v1/ops/in-call-data-use/{provider}  attest one; step-up
                                               `attest_in_call_data_use:<provider>`

WHY A SEPARATE ATTESTATION (D-839, founder 20 Oct 2026). When our own model is on (D-764),
every turn of every call sends what the caller said through our Google key. The dashboard
attestation (`dashboard_data_use_routes.py`, D-477) is about Pip's screen text; an operator's
word on that is not a word on callers' voices, so this leg has its own statement, step-up and
append-only rows (`ops/models.PlatformInCallDataUse`), and own-model readiness
(`agents/own_model.own_model_readiness`) reads THIS one. The three facts are the dashboard
form's, for the reasons `ops/models.PlatformDashboardDataUse` gives.

`platform:config`, as the dashboard attestation: configuration, not a credential.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Final

from calevate_shared.engine import LlmProvider
from fastapi import APIRouter, Depends, Header, Path, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.own_model import OWN_MODEL_PROVIDER
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import global_db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.core.stepup import StepUpGate
from apps.api.ops.dashboard_data_use_routes import DashboardDataUseAttestIn
from apps.api.ops.model_pricing import (
    DataUseAttestation,
    attest_data_use,
    data_use_attestations,
)

router = APIRouter(prefix="/v1/ops/in-call-data-use", tags=["ops"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]
DataUseOperator = Annotated[Principal, Depends(requires("platform:config", realm="admin"))]
ProviderId = Annotated[str, Path(max_length=48, pattern=r"^[a-z][a-z0-9_]*$")]

#: The providers a call can answer on through our key: our own model's (D-764).
IN_CALL_PROVIDERS: Final[tuple[LlmProvider, ...]] = (OWN_MODEL_PROVIDER,)

#: What the operator is putting their name to, rendered verbatim above the form. It makes no
#: claim about what any vendor's terms say (hard rule 11): it names checks an operator makes
#: in the vendor's own console.
IN_CALL_STATEMENT: Final = (
    "I have opened this provider's own console and checked the account our API key for it "
    "belongs to. When our own model answers calls, what every caller says on every turn is "
    "sent through this key. I confirm (1) the project or account named below is the one that "
    "key belongs to; (2) it is on the vendor's PAID tier — for Google, the 'Billing Tier' "
    "column on the AI Studio Projects page shows the project linked to an open billing "
    "account; and (3) nothing on that account opts our submitted content back into the "
    "vendor's free-tier data terms — for Google, Gemini API Logs/Datasets sharing is OFF. "
    "This attestation is about TRAINING on what callers say only: it does not say the vendor "
    "keeps no logs, that no employee may ever read flagged content, or that anything is "
    "stored in India."
)


def attest_confirmation(provider: str) -> str:
    """The step-up string for one provider's in-call attestation, bound to the provider."""
    return f"attest_in_call_data_use:{provider}"


class InCallDataUseOut(BaseModel):
    """One provider, as the panel renders it. The attestation fields are all `null` together
    when nobody has attested, a distinct state from an attested "no"."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    #: The latest attestation confirms both answers, so caller speech may go to this vendor
    #: through our key; own-model readiness reads this for our model's provider.
    permits: bool
    vendor_account_ref: str | None
    paid_tier_confirmed: bool | None
    no_training_opt_in_confirmed: bool | None
    attested_at: str | None
    attested_by: str | None
    source_note: str | None


class InCallDataUseListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    providers: list[InCallDataUseOut]
    statement: str


class InCallDataUseWriteOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: InCallDataUseOut


def _row(provider: str, attested: DataUseAttestation | None) -> InCallDataUseOut:
    return InCallDataUseOut(
        provider=provider,
        permits=attested is not None and attested.permits,
        vendor_account_ref=attested.vendor_account_ref if attested else None,
        paid_tier_confirmed=attested.paid_tier_confirmed if attested else None,
        no_training_opt_in_confirmed=attested.no_training_opt_in_confirmed if attested else None,
        attested_at=attested.attested_at.isoformat() if attested else None,
        attested_by=attested.attested_by if attested else None,
        source_note=attested.source_note if attested else None,
    )


@router.get(
    "",
    response_model=InCallDataUseListOut,
    openapi_extra=permission_meta("platform:config"),
    summary="Each in-call provider's latest data-use attestation for caller speech",
    description=(
        "Lists each provider a call can answer on through our key, whether its latest "
        "attestation permits sending what callers say, and that attestation. Our own model "
        "cannot be switched on until its provider's row permits it."
    ),
)
async def list_in_call_data_use(session: GlobalSession, _: DataUseOperator) -> InCallDataUseListOut:
    attested = await data_use_attestations(session, leg="in_call")
    return InCallDataUseListOut(
        providers=[_row(provider, attested.get(provider)) for provider in IN_CALL_PROVIDERS],
        statement=IN_CALL_STATEMENT,
    )


@router.post(
    "/{provider}",
    response_model=InCallDataUseWriteOut,
    openapi_extra=permission_meta("platform:config"),
    summary="Attest one provider's data-use position for caller speech (step-up, audited)",
    description=(
        "Records what you read in the vendor's own console as a NEW dated row; a correction "
        "is a later attestation, never an edit. Requires "
        "`X-Confirm-Action: attest_in_call_data_use:<provider>`. A negative answer is "
        "recorded too, and keeps our own model from being switched on."
    ),
)
async def attest_provider_in_call_data_use(
    payload: DashboardDataUseAttestIn,
    session: GlobalSession,
    request: Request,
    principal: DataUseOperator,
    provider: ProviderId,
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> InCallDataUseWriteOut:
    step_up.require(x_confirm_action, attest_confirmation(provider))
    if provider not in IN_CALL_PROVIDERS:
        raise ProblemError(
            kind="not_found",
            code="in_call_data_use_unknown_provider",
            title="No call answers on this provider through our key",
            detail=f"{provider!r} is not a provider our own model answers calls on.",
            remediation="The providers are " + ", ".join(IN_CALL_PROVIDERS) + ".",
        )
    if principal.user_id is None:
        raise ProblemError(
            kind="auth",
            code="in_call_data_use_actor_unknown",
            title="This session has no admin identity",
            detail="An attestation has to be attributable to an operator.",
        )
    attested = await attest_data_use(
        session,
        provider=provider,
        vendor_account_ref=payload.vendor_account_ref,
        paid_tier_confirmed=payload.paid_tier_confirmed,
        no_training_opt_in_confirmed=payload.no_training_opt_in_confirmed,
        attested_at=datetime.now(UTC),
        source_note=payload.source_note,
        actor_id=principal.user_id,
        leg="in_call",
    )
    await write_audit(
        session,
        action="platform.in_call_data_use_attested",
        actor=principal,
        object_type="platform_in_call_data_use",
        object_id=provider,
        ip=client_request_ip(request),
        summary={
            "provider": provider,
            "vendor_account_ref": attested.vendor_account_ref,
            "paid_tier_confirmed": attested.paid_tier_confirmed,
            "no_training_opt_in_confirmed": attested.no_training_opt_in_confirmed,
            "source_note": attested.source_note,
        },
    )
    return InCallDataUseWriteOut(provider=_row(attested.provider, attested))


__all__ = ["IN_CALL_PROVIDERS", "IN_CALL_STATEMENT", "attest_confirmation", "router"]
