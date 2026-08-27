"""The operator's attestation about an LLM provider's DATA-USE terms for the dashboard leg.

    GET  /v1/ops/dashboard-data-use             every declared leg: whether the dashboard
                                                 assistant may run on it, why not, and the
                                                 latest attestation if there is one
    POST /v1/ops/dashboard-data-use/{provider}  attest one leg; step-up
                                                 `attest_dashboard_data_use:<provider>`

WHY THIS EXISTS AND WHY IT IS AN ATTESTATION RATHER THAN A CHECK (D-477). The dashboard AI
assistant prefers the provider a CLIENT's own agents run on, and whether it MAY is a question
about the vendor's terms for OUR account — not about a model's merit, not about a credential
being present. Every Google-owned host is egress-blocked from this deployment (re-measured
27 Aug 2026), and no primary source about any vendor's data-use position could be read from
here. So the answer arrives the way the LLM price already does and the way the Azure
resource's region already does (OPERATIONS §2 gates 20/20c): a person reads it in the vendor's
console and puts their name to it, with the account it is about captured as a first-class
field so the claim can be re-checked later rather than only re-made.

**IT IS THREE FACTS, NOT A SIGNATURE**, and `ops/models.PlatformDashboardDataUse` argues each
one at length: the vendor project the key belongs to, whether that project is on the paid
tier, and whether anything on it opts submitted content back into the vendor's unpaid terms.
A form that asked only the middle question would pass a project that had opted its logs into
training.

⚠ **ATTESTING DOES NOT BY ITSELF MOVE THE ASSISTANT ONTO A PROVIDER**, and the response says
so in `blocked_reason` rather than leaving an operator to find out. Eligibility is the AND of
this attestation and `agents/llm_models.DASHBOARD_ADDRESSABLE_PROVIDERS` — whether this
repository can build a dashboard chat request for the leg at all — and today only the Azure
leg satisfies the second. The screen states both grounds because
`ops/model_pricing.ModelOfferability.withheld_reason` exists for exactly the failure of not
stating them: a panel inviting an operator to do a five-minute job that cannot succeed.

⚠ **THIS SURFACE DOES NOT GOVERN THE IN-CALL LEG, WHICH IS LIVE TODAY.** In-call sends RAW
CALLER SPEECH to whatever provider a client's chosen model sits on — strictly worse exposure
than this leg's redacted screen text — and nothing here gates it. OPERATIONS §2 gate 41 is
where that question is owned; it is the founder's to answer, not a column's.

WHY `platform:config` AND NOT `platform:secrets`: `model_price_routes.py`'s reason exactly —
an attestation is configuration, not a credential. It is visible, revertible (by a superseding
attestation) and carries no secret; a project id is an account label, not an authenticator.
Both permissions are superadmin-only, so "only the super admin reaches this panel" holds
either way.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, get_args

from calevate_shared.engine import LlmProvider
from fastapi import APIRouter, BackgroundTasks, Depends, Header, Path, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.llm_models import (
    DASHBOARD_ADDRESSABLE_PROVIDERS,
    dashboard_leg_reason,
)
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import global_db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.core.stepup import StepUpGate
from apps.api.ops.model_pricing import (
    DashboardDataUseAttestation,
    attest_dashboard_data_use,
    dashboard_data_use_attestations,
)
from apps.api.ops.pricing_snapshot import refresh_pricing_snapshot

router = APIRouter(prefix="/v1/ops/dashboard-data-use", tags=["ops"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]
DataUseOperator = Annotated[Principal, Depends(requires("platform:config", realm="admin"))]

#: A provider on the wire. Bounded and character-classed because it is interpolated into a
#: step-up string and an audit summary. NOT an allow-list of the declared legs: the service
#: refuses an undeclared one by name, and a second copy of that vocabulary here is the drift
#: this route avoids (`ModelId`'s argument in `model_price_routes.py`).
ProviderId = Annotated[str, Path(max_length=48, pattern=r"^[a-z][a-z0-9_]*$")]

#: WHAT THE OPERATOR IS PUTTING THEIR NAME TO, rendered verbatim above the form.
#:
#: ⚠ **PLACEHOLDER WORDING — TO BE FINALISED BY THE FOUNDER.** It is written to describe the
#: TWO CHECKS in terms an operator can perform, and it deliberately makes NO claim about what
#: any vendor's terms say: every Google-owned host is egress-blocked from this environment, so
#: this repository has read none of them first-hand and hard rule 11 forbids asserting them.
#: The concrete instruction for Google — the Billing Tier column on AI Studio's Projects page
#: — comes from a SECONDARY reading relayed into this tree, not from a page read here.
ATTESTATION_STATEMENT: str = (
    "I have opened this provider's own console and checked the account our API key for it "
    "belongs to. I confirm (1) the project or account named below is the one that key "
    "belongs to; (2) it is on the vendor's PAID tier — for Google, the 'Billing Tier' column "
    "on the AI Studio Projects page shows the project linked to an open billing account; and "
    "(3) nothing on that account opts our submitted content back into the vendor's free-tier "
    "data terms — for Google, Gemini API Logs/Datasets sharing is OFF. I understand this "
    "attestation is about TRAINING on submitted content only: it does not say the vendor "
    "keeps no logs, that no employee may ever read flagged content, or that anything is "
    "stored in India."
)


def attest_confirmation(provider: str) -> str:
    """The step-up string for attesting ONE provider's data-use position.

    A named function with a test pinning the literal, like `model_price_routes
    .attest_confirmation`: it is an ops procedure a runbook prints. Bound to the PROVIDER, so
    a header captured for Google cannot be replayed against OpenAI.
    """
    return f"attest_dashboard_data_use:{provider}"


class DashboardDataUseOut(BaseModel):
    """One declared leg, as the panel renders it.

    NO FIELD CARRIES A DEFAULT, the rule every ops panel model here follows: every fact the
    console must trust is required on the wire, and `null` is used where the answer genuinely
    has no value — which for `attested_at` means "nobody has looked", a real and distinct
    state from an operator having looked and found a problem.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str
    #: May the dashboard assistant run on this leg right now — the AND of the attestation and
    #: whether this repository can build a request for the leg at all.
    eligible: bool
    #: Why not, in the operator's language. `null` exactly when `eligible`.
    blocked_reason: str | None
    #: Can this repository build a dashboard chat request for the leg at all? Reported
    #: SEPARATELY from `eligible` so the panel can say plainly that attesting will not, on its
    #: own, switch the assistant onto this provider.
    dashboard_leg_built: bool
    #: The latest attestation. Every field `null` together when there has never been one.
    vendor_account_ref: str | None
    paid_tier_confirmed: bool | None
    no_training_opt_in_confirmed: bool | None
    attested_at: str | None
    attested_by: str | None
    source_note: str | None


class DashboardDataUseListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    providers: list[DashboardDataUseOut]
    #: The exact sentence the operator is agreeing to, so the form renders it verbatim rather
    #: than the console keeping its own copy that drifts from the server's.
    statement: str


class DashboardDataUseAttestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The vendor project/account our key for this provider belongs to. Required — without it
    #: the claim can never be re-checked, only re-made.
    vendor_account_ref: str = Field(min_length=1, max_length=200)
    paid_tier_confirmed: bool
    no_training_opt_in_confirmed: bool
    #: WHERE the operator looked, in their own words. The evidence that makes this an
    #: attestation rather than a guess, and the reason recorded in `audit_log`.
    source_note: str = Field(min_length=3, max_length=500)

    @field_validator("vendor_account_ref", "source_note")
    @classmethod
    def _not_whitespace(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("this field cannot be blank")
        return stripped


class DashboardDataUseWriteOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: DashboardDataUseOut


def _row(
    provider: LlmProvider,
    attested: DashboardDataUseAttestation | None,
    permitted: frozenset[LlmProvider],
) -> DashboardDataUseOut:
    # `permitted` comes from the STORE this request just read, not from the process
    # snapshot: an operator who has just attested and is shown the unchanged ground would
    # reasonably conclude their write did not land. See `dashboard_leg_reason`.
    reason = dashboard_leg_reason(provider, attested=permitted)
    return DashboardDataUseOut(
        provider=provider,
        eligible=reason is None,
        blocked_reason=reason,
        dashboard_leg_built=provider in DASHBOARD_ADDRESSABLE_PROVIDERS,
        vendor_account_ref=attested.vendor_account_ref if attested else None,
        paid_tier_confirmed=attested.paid_tier_confirmed if attested else None,
        no_training_opt_in_confirmed=(attested.no_training_opt_in_confirmed if attested else None),
        attested_at=attested.attested_at.isoformat() if attested else None,
        attested_by=attested.attested_by if attested else None,
        source_note=attested.source_note if attested else None,
    )


@router.get(
    "",
    response_model=DashboardDataUseListOut,
    openapi_extra=permission_meta("platform:config"),
    summary="Every LLM leg's dashboard-assist eligibility and its latest data-use attestation",
    description=(
        "Lists every declared LLM leg with whether the in-app AI assistant may run on it, "
        "the ground if it may not, and the latest operator attestation about that vendor's "
        "data-use terms. Eligibility needs BOTH an attestation and a dashboard leg this "
        "platform can actually build — `dashboard_leg_built` says whether the second is "
        "true, so attesting a provider whose leg is not built is not mistaken for enabling "
        "it. This surface does not govern the in-call leg, which sends raw caller speech."
    ),
)
async def list_dashboard_data_use(
    session: GlobalSession, _: DataUseOperator
) -> DashboardDataUseListOut:
    attested = await dashboard_data_use_attestations(session)
    permitted = frozenset(p for p, a in attested.items() if a.permits_dashboard)
    return DashboardDataUseListOut(
        providers=[
            _row(provider, attested.get(provider), permitted)
            for provider in sorted(get_args(LlmProvider))
        ],
        statement=ATTESTATION_STATEMENT,
    )


@router.post(
    "/{provider}",
    response_model=DashboardDataUseWriteOut,
    openapi_extra=permission_meta("platform:config"),
    summary="Attest one LLM leg's data-use position for the dashboard assist (step-up, audited)",
    description=(
        "Records what you read in the vendor's own console as a NEW dated row — a correction "
        "is a later attestation, never an edit, so what was believed at the time a client's "
        "content reached that vendor stays answerable. Requires "
        "`X-Confirm-Action: attest_dashboard_data_use:<provider>`. A negative answer is worth "
        "recording too: 'somebody looked and it is not on the paid tier' is a different and "
        "more useful state than 'nobody has looked'."
    ),
)
async def attest_provider_data_use(
    payload: DashboardDataUseAttestIn,
    session: GlobalSession,
    request: Request,
    tasks: BackgroundTasks,
    principal: DataUseOperator,
    provider: ProviderId,
    # Resolved BEFORE this handler body runs, so the session read cannot happen inside an
    # open transaction — `core/stepup.py` on `max_overflow=0`.
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> DashboardDataUseWriteOut:
    """One attestation in, one audit row, in the same transaction."""
    step_up.require(x_confirm_action, attest_confirmation(provider))
    if principal.user_id is None:
        # `attested_by` is NOT NULL and references `admin_users`: every row here was typed by
        # a person. Refusing explicitly turns an impossible state into a sentence rather than
        # an integrity error rendered as a 500.
        raise ProblemError(
            kind="auth",
            code="dashboard_data_use_actor_unknown",
            title="This session has no admin identity",
            detail="An attestation has to be attributable to an operator.",
        )
    attested = await attest_dashboard_data_use(
        session,
        provider=provider,
        vendor_account_ref=payload.vendor_account_ref,
        paid_tier_confirmed=payload.paid_tier_confirmed,
        no_training_opt_in_confirmed=payload.no_training_opt_in_confirmed,
        attested_at=datetime.now(UTC),
        source_note=payload.source_note,
        actor_id=principal.user_id,
    )
    await write_audit(
        session,
        action="platform.dashboard_data_use_attested",
        actor=principal,
        object_type="platform_dashboard_data_use",
        object_id=provider,
        ip=client_request_ip(request),
        # The change itself: the leg, the account it is about, both answers and the operator's
        # stated evidence. No secret, no PII — a project id is an account label.
        summary={
            "provider": provider,
            "vendor_account_ref": attested.vendor_account_ref,
            "paid_tier_confirmed": attested.paid_tier_confirmed,
            "no_training_opt_in_confirmed": attested.no_training_opt_in_confirmed,
            "source_note": attested.source_note,
        },
    )
    # Refresh the process snapshot AFTER the request's transaction commits, so the new
    # attestation reaches the assist selector on the next read rather than waiting a full poll
    # interval — `model_price_routes`' shape, and survivable if it fails.
    tasks.add_task(refresh_pricing_snapshot)
    permitted = frozenset({attested.provider}) if attested.permits_dashboard else frozenset()
    return DashboardDataUseWriteOut(provider=_row(attested.provider, attested, permitted))


__all__ = ["ATTESTATION_STATEMENT", "attest_confirmation", "router"]
