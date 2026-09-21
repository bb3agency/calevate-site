"""Client-realm read of this account's own KYC verification (R-11; SURFACES §2b).

The view that explains a disabled dial button, and what we hold about this business.
`compliance.service.check_dispatch` emits `kyc_missing` / `kyc_not_verified`, and the
client's own operator will ask for the same documents before it issues them a connection
at all; without this route a client who hit either had nowhere to look up what we hold,
what state it is in, or what we are waiting for. That is the page somebody opens
precisely when they are already blocked, which is the worst possible moment to have no
page.

Four shapes, each deliberate — the same four `registration_routes.py` argues for, so
that a client's two compliance screens behave identically:

- **`org:read`, not `org:manage`.** Looking at your own compliance state is not changing
  it. `org:manage` is in `MUTATING_PERMISSIONS`, so requiring it would make this
  invisible to a support person inside a read-only "view as client" session (D-22) —
  exactly the person on the call when the account is blocked, and exactly the recurring
  bug `tests/impersonation_reads_test.py` exists to stop.
- **A missing record is a 200, not a 404.** It is the normal state of every new account.
  The console renders "not verified yet" from `recorded: false`; a 404 arrives at the
  fetch layer indistinguishable from a moved route or a lost permission.
- **A client still cannot SET their own status** (D-47, narrowed by D-635). A client who
  could mark themselves `verified` would be opening the telecom gate on a verification
  that never happened — the argument that keeps `record_dlt_registration` admin-only, and
  a sharper one here, since this gate stands between an anonymous signup and a phone
  connection (Telecom Act 2023 s.3(7)). What D-635 adds is a client-realm route that
  STARTS a verification: it writes a `kyc_verification_requests` row and nothing else,
  and the only thing that can move `kyc_records` is a signed delivery from the provider.
  The guarantee is unchanged; what enforces it moved from "there is no route" to "the
  route cannot assert the outcome".
- **No audit row.** This discloses no personal data — a business's own verification
  state, to that business — and it is the page a blocked client will refresh. An audit
  chain that grows a row per poll stops being readable.

`number_purchase_available` is on this response rather than on a second endpoint because
it is half of the answer to "can Calevate get me a number": the other half is whether
this product supplies numbers at all, and under Model B it does not — the client buys the
connection on their own operator account and stays the subscriber of record
(`docs/legal/LEGAL-OPS-PLAYBOOK.md` §9). It comes from
`campaigns.provisioning.number_purchase_available()` — the SAME selector
`POST /v1/numbers/purchase` asks — so this screen can never offer a button that route
refuses. It is false for every account in every deployment, and the screen renders a
sentence rather than a control because of it.

Hard rule 1: the session is `deps.db`, so the row is scoped by RLS rather than by a
predicate anyone could forget. `tests/kyc_gate_test.py` proves tenant B sees zero rows
both through this route and on the raw session.

Hard rule 6: `document_ref` is a public business-registry identifier; `signatory_name`
and `verified_name` are the names of the person who signed for the entity and the person
a licensed aggregator attested, both of which that entity already knows. No
identity-document number exists in the schema to leak, and a CHECK on every reference and
name column refuses one being typed in. Names are returned to the account they belong to
and appear in no log line and no audit summary.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns.provisioning import number_purchase_available
from apps.api.compliance.audit import write_audit
from apps.api.compliance.kyc import KycRecord, read_kyc
from apps.api.compliance.kyc_providers import available_provider
from apps.api.compliance.kyc_verification import (
    VERIFICATION_UNAVAILABLE_REASON,
    apply_outcome,
    expire_stale_runs,
    open_request,
    resolve_request,
)
from apps.api.compliance.models import KYC_ENTITY_TYPES
from apps.api.core.alerting import alert
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.console_links import console_base
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session, untenanted_session

router = APIRouter(prefix="/v1/compliance/kyc", tags=["compliance"])

Session = Annotated[AsyncSession, Depends(db)]
# `Annotated` aliases rather than `Depends(...)` defaults: B008 is waived only for
# `**/routes.py` and this module is `kyc_routes.py` — same situation, same resolution as
# `registration_routes.py`, `dnc_routes.py` and `deletion_routes.py`.
KycReader = Annotated[Principal, Depends(requires("org:read"))]
# STARTING a verification is a mutation of this account's compliance state, so it
# takes the mutating permission — and being in `MUTATING_PERMISSIONS` is also what
# keeps it out of a read-only "view as client" session, which is correct: an operator
# must not begin an identity verification on a client's behalf.
KycWriter = Annotated[Principal, Depends(requires("org:manage"))]


class KycRecordOut(BaseModel):
    """This account's identity verification, as ops last recorded it.

    Every field except `recorded`, `is_verified` and `number_purchase_available` is
    nullable, because all of them are genuinely absent before anything is filed.
    `is_verified` is computed server-side for the same reason `PeRegistrationOut`'s
    `is_active` is: "is `in_review` good enough" is a question the console must not
    answer for itself, and this response and the dispatch gate must never disagree.
    """

    model_config = ConfigDict(extra="forbid")

    recorded: bool
    status: str | None
    entity_type: str | None
    # WHAT was checked and its public registry reference — CIN, LLPIN, GSTIN, Udyam. The
    # document itself is never held by us; `evidence_ref` says where the pack is filed.
    document_kind: str | None
    document_ref: str | None
    signatory_name: str | None
    evidence_ref: str | None
    # WHY this account is blocked, when the answer is "we looked and said no". Present
    # exactly when `status = 'rejected'` — the CHECK constraint guarantees it is not
    # null in that state, so a client is never told "rejected" with no reason.
    rejection_reason: str | None
    submitted_at: datetime | None
    # When WE verified it, stamped by the database at the moment of the write — not a
    # date an operator typed.
    verified_at: datetime | None
    # WHO verified, and the aggregator's own reference (D-635). The reference is the
    # liability artefact — a licensed third party can be asked to corroborate it — and
    # `verified_name` is what they attested. Returned to the account they describe and
    # to nobody else.
    verification_source: str | None
    verification_provider: str | None
    verification_reference: str | None
    verified_name: str | None
    is_verified: bool
    # Whether this deployment can run a self-service verification at all. The SAME
    # selector `POST /v1/compliance/kyc/verification` asks, so this screen can never
    # offer a button that route refuses — the discipline `number_purchase_available`
    # already establishes one field down. False on every deployment today.
    self_verification_available: bool
    # Both halves of "can Calevate get me a number": this account being verified AND
    # this product supplying numbers at all. The second half is FALSE BY DECISION and
    # not by omission — Model B, `campaigns/provisioning.py` — so this is false for
    # every account in every deployment.
    number_purchase_available: bool


def _out(
    record: KycRecord, *, purchase_available: bool, self_verification_available: bool
) -> KycRecordOut:
    return KycRecordOut(
        recorded=record.recorded,
        status=record.status,
        entity_type=record.entity_type,
        document_kind=record.document_kind,
        document_ref=record.document_ref,
        signatory_name=record.signatory_name,
        evidence_ref=record.evidence_ref,
        rejection_reason=record.rejection_reason,
        submitted_at=record.submitted_at,
        verified_at=record.verified_at,
        verification_source=record.verification_source,
        verification_provider=record.verification_provider,
        verification_reference=record.verification_reference,
        verified_name=record.verified_name,
        is_verified=record.is_verified,
        self_verification_available=self_verification_available,
        number_purchase_available=purchase_available,
    )


@router.get(
    "",
    response_model=KycRecordOut,
    openapi_extra=permission_meta("org:read"),
    summary="This account's identity verification — absence is data, not a 404",
    description=(
        "What Calevate has verified about this business. Read-only: Indian telecom "
        "rules make the subscriber's identity something the provider verifies, never "
        "something the subscriber asserts, so verification is recorded by Calevate "
        "operations. `number_purchase_available` is always false — Calevate does not "
        "supply telephone numbers; the client takes the connection on their own "
        "operator account. A business with nothing on file yet gets `recorded: false` "
        "and a 200."
    ),
)
async def read_kyc_record(
    session: Session,
    principal: KycReader,
) -> KycRecordOut:
    assert principal.tenant_id is not None
    record = await read_kyc(session, tenant_id=principal.tenant_id)
    return _out(
        record,
        purchase_available=record.is_verified and number_purchase_available(),
        self_verification_available=available_provider().available,
    )


# ---------------------------------------------------------------------------
# D-635 — the client verifies THEMSELVES, and the result comes back on a webhook.
#
# D-47 said there is "deliberately no client-realm write" here, and that clause is what
# this supersedes — narrowly. A client still cannot SET their status: `start_verification`
# writes a request row and nothing else, and the only thing that can move `kyc_records` is
# a signed delivery from the provider. The property D-47 was protecting — that a client
# cannot mark the telecom gate green on a verification that never happened — is unchanged
# and is now enforced by a signature rather than by the absence of a route.
# ---------------------------------------------------------------------------


class StartVerificationIn(BaseModel):
    """How the business is constituted — the only thing the client tells us.

    It decides the BRANCH, not the outcome: a sole proprietor's verification completes
    the record, a company's verifies the authorised signatory and leaves the registry
    check to an operator. It is not taken on trust in any way that matters, because a
    company's row cannot reach `verified` on this path at all.
    """

    model_config = ConfigDict(extra="forbid")

    entity_type: str


class StartVerificationOut(BaseModel):
    """Where to send the client, and what we will know the run by."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    provider_ref: str
    #: The PROVIDER's page. The client authenticates there and their Aadhaar never
    #: touches this system — which is the whole architecture, in one field.
    redirect_url: str


@router.post(
    "/verification",
    response_model=StartVerificationOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Begin verifying this business's identity with a licensed aggregator",
    description=(
        "Opens a verification run and returns the provider URL to send the signed-in "
        "user to. Calevate receives only whether it succeeded, the provider's reference "
        "and the verified name — never an Aadhaar number, a PAN or a document. A sole "
        "proprietorship is verified outright; for any other entity type this verifies "
        "the authorised signatory and Calevate operations still checks the business "
        "against its public registry entry."
    ),
)
async def start_verification(
    body: StartVerificationIn,
    request: Request,
    session: Session,
    principal: KycWriter,
) -> StartVerificationOut:
    assert principal.tenant_id is not None
    if body.entity_type not in KYC_ENTITY_TYPES:
        raise ProblemError.business_rule(
            "unknown_entity_type",
            "That is not an entity type we can verify.",
            remediation="Choose how the business is registered and try again.",
        )
    capability = available_provider()
    if capability.provider is None:
        # The SAME selector the read route reports, so a screen can never offer a button
        # this refuses. The machine reason goes in the code; the sentence is the one
        # `kyc_verification.py` defines, so this condition is explained identically
        # wherever it surfaces.
        raise ProblemError.business_rule(
            "self_verification_unavailable",
            VERIFICATION_UNAVAILABLE_REASON,
            remediation="Our operations team will verify this business directly.",
        )
    record = await read_kyc(session, tenant_id=principal.tenant_id)
    if record.is_verified:
        raise ProblemError.business_rule(
            "kyc_already_verified",
            "This business's identity is already verified.",
            remediation="Nothing further is needed.",
        )
    if record.entity_type is not None and record.entity_type != body.entity_type:
        # THE DECLARATION DOES NOT OVERRULE WHAT IS ON FILE. The entity type decides the
        # BRANCH, and only `sole_proprietorship` reaches `verified` on one person's
        # DigiLocker authentication — so a company declaring itself a proprietorship is
        # the one input on this route that could verify a business nobody checked. Where
        # an operator has already recorded how the business is constituted, a contradiction
        # is refused rather than silently overwritten by `record_kyc`'s upsert.
        raise ProblemError.business_rule(
            "entity_type_on_file_differs",
            "Our record of how this business is registered does not match what you "
            "selected, so we cannot start a verification against it.",
            remediation="Contact support to correct the registered entity type before verifying.",
        )

    provider = capability.provider
    start = await provider.start(
        entity_type=body.entity_type,
        redirect_back_url=await _return_url(session, tenant_id=principal.tenant_id),
    )
    # This tenant's abandoned runs, closed on the way past. One of the two writers of
    # `expired` — the other is the webhook — which is why there is no sweep to schedule.
    await expire_stale_runs(session, tenant_id=principal.tenant_id)
    # The row is committed BEFORE the client can possibly reach the provider, because the
    # webhook has no other way to learn whose run this is. `open_request` argues the
    # ordering in full.
    await open_request(
        session,
        tenant_id=principal.tenant_id,
        provider=provider.name,
        provider_ref=start.provider_ref,
        entity_type=body.entity_type,
    )
    await write_audit(
        session,
        action="kyc.self_verification_started",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="kyc_verification_request",
        object_id=start.provider_ref,
        ip=client_request_ip(request),
        summary={"provider": provider.name, "entity_type": body.entity_type},
    )
    return StartVerificationOut(
        provider=provider.name, provider_ref=start.provider_ref, redirect_url=start.redirect_url
    )


async def _return_url(session: AsyncSession, *, tenant_id: UUID) -> str:
    """Where the provider sends the client afterwards — built ENTIRELY server-side.

    The slug is read rather than accepted from the request body. A caller-supplied return
    URL on a route that redirects a signed-in user is an open redirect, and one on the
    identity-verification path is the most valuable possible place to have one: the
    phishing page it lands on is the page the user is already expecting to type credentials
    into.
    """
    row = (
        await session.execute(
            text("SELECT slug FROM organizations WHERE id = :tid"), {"tid": tenant_id}
        )
    ).first()
    slug = str(row[0]) if row is not None else ""
    return f"{console_base('client')}/c/{slug}/verification"


# --- The receiver -----------------------------------------------------------

webhook_router = APIRouter(prefix="/hooks/v1/kyc", tags=["compliance"])


class VerificationAck(BaseModel):
    """What the provider is told. Deliberately says nothing about the tenant or the
    person — an ack is read by whoever can reach the endpoint, which is everyone."""

    model_config = ConfigDict(extra="forbid")

    status: str


@webhook_router.post(
    "/{provider}",
    response_model=VerificationAck,
    summary="Verification outcome from the configured identity aggregator",
    description=(
        "Signed webhook. The signature is verified over the raw bytes before anything is "
        "parsed; the tenant is resolved from the run Calevate opened, never from the "
        "payload; and a redelivery is acknowledged without changing anything."
    ),
)
async def receive_verification_outcome(provider: str, request: Request) -> VerificationAck:
    """An unauthenticated endpoint that can mark a client VERIFIED — so it fails closed
    at every step, and each step refuses for its own reason.

    Nothing durable is written until the signature verifies AND the run resolves, so a
    forged or misaddressed delivery leaves no row at all — not even a trace it could
    later be replayed from.

    The body is NOT bounded here: `core/middleware`'s body-size middleware bounds every
    route in the app, including the ones nobody thought to bound, and a second cap on
    this one would be a second mechanism for a solved problem that could later disagree
    with the first.
    """
    capability = available_provider()
    if capability.provider is None:
        # A deployment with no configured, credentialled provider has no verification
        # feed, and something is POSTing to it. 404 rather than 503: an unconfigured
        # endpoint should not confirm to a prober that it exists and is merely waiting
        # for a secret.
        alert("ROUTE_HANDLER", "kyc_webhook_unconfigured", reason=capability.reason or "unknown")
        raise ProblemError.not_found("verification endpoint")
    if provider != capability.provider.name:
        # The path names a provider this deployment is not on. Refused rather than
        # ignored: it is either a stale endpoint still configured at an old vendor, or
        # somebody trying every provider name to find one that answers.
        alert("ROUTE_HANDLER", "kyc_webhook_wrong_provider", provider=provider)
        raise ProblemError.not_found("verification endpoint")

    raw = await request.body()
    if not capability.provider.verify_webhook(raw=raw, headers=_lowercased(request.headers)):
        # The one refusal that must never be softened. A forged delivery here marks an
        # arbitrary account verified, which defeats the entire control and the liability
        # case built on it.
        alert("ROUTE_HANDLER", "kyc_webhook_bad_signature", provider=provider)
        raise ProblemError.unauthorized("Signature verification failed.")

    try:
        outcome = capability.provider.parse_outcome(raw=raw)
    except (ValueError, KeyError):
        # Past the signature the sender is genuine, so an unreadable body is OUR problem
        # to see rather than theirs to retry into silence.
        alert("ROUTE_HANDLER", "kyc_webhook_unreadable_payload", provider=provider)
        raise ProblemError.business_rule(
            "verification_payload_unreadable", "That verification result could not be read."
        ) from None

    async with untenanted_session() as lookup:
        run = await resolve_request(lookup, provider=provider, provider_ref=outcome.provider_ref)
    if run is None:
        # A correctly-signed outcome for a run we never opened. There is no race that
        # produces this — the row is committed before the client can reach the provider —
        # so it is either a replay against a purged row or a vendor misconfiguration
        # pointing another customer's traffic at us. Either way there is no tenant, and
        # inventing one is the only truly unrecoverable mistake available here.
        alert("ROUTE_HANDLER", "kyc_webhook_unknown_reference", provider=provider)
        raise ProblemError.not_found("verification run")

    async with tenant_session(run.tenant_id) as session:
        result = await apply_outcome(session, request=run, provider=provider, outcome=outcome)
    if result == "expired":
        # Post-signature, so the provider is genuine and something is reporting on a run
        # that outlived its window. Either their delivery is days late or somebody is
        # spending an old reference; both are worth a person's attention, and neither
        # verified anybody.
        alert("ROUTE_HANDLER", "kyc_webhook_expired_run", provider=provider)
    return VerificationAck(status=result)


def _lowercased(headers: Mapping[str, str]) -> dict[str, str]:
    """Header names, case-folded once. HTTP header names are case-insensitive and an
    adapter that compared them raw would work against one provider's capitalisation and
    fail against the next one's."""
    return {key.lower(): value for key, value in headers.items()}


__all__ = ["router", "webhook_router"]
