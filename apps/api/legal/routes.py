"""Agreements & readiness — the client's own view of what stands between them and dialling.

    GET  /v1/legal/readiness     everything at once: documents, acceptance state, blockers
    POST /v1/legal/acceptances   the owner accepts one document at one version

THE SERVER DECIDES EVERY PIECE OF STATE AND SUPPLIES THE SENTENCE FOR IT. That is the
doctrine `apps/web/src/lib/api/aiQuota.ts` states for the dashboard AI and
`compliance/kyc.py` states for `is_verified`, and it binds harder here than in either:
whether an organisation may operate is a COMPLIANCE verdict that four gates already
compute, and a browser that re-derived it from a list of documents would eventually
disagree with the gate that actually refuses the call. So `may_operate`, every
document's `state`, every blocker's `title`/`actor`/`next_step` and the acceptance
wording all arrive decided; the console renders and never computes.

WHO MAY READ, WHO MAY ACCEPT
----------------------------
The read is `org:read`, which BOTH client roles hold and which is not in
`MUTATING_PERMISSIONS` — so a member who cannot accept can still see what is outstanding,
and the screen keeps working inside a D-22 read-only "view as client" session. That is the
session a support person is in exactly when this account's calls are blocked, and
`tests/impersonation_reads_test.py` exists because the opposite mistake has now been made
three times in three modules. Choosing the permission is only HALF of keeping that
promise: see the note on `Reader` below for the half that is the realm declaration, and
which had this screen refusing a view-as session outright while this paragraph said it
did not.

The write is `org:manage`, client realm. That IS "only the organisation owner", stated in
the vocabulary this repo already uses rather than by a hand-typed role check:
`memberships.role` is `owner`/`staff` (`tenancy/models.MEMBER_ROLES`), `ROLE_PERMISSIONS`
gives `org:manage` to `owner` alone, and `tests/legal_agreements_test.py` asserts that
equality so the gate cannot widen by somebody adding a permission to `staff`. Two further
consequences fall out of the same declaration and both are wanted: `org:manage` is in
`MUTATING_PERMISSIONS`, so an impersonating operator cannot accept a client's agreements
while wearing their face; and `realm="client"` means an operator cannot accept them from
the admin console either. Nobody signs for the client but the client.

WHY THERE IS NO `Idempotency-Key` ON THE POST
---------------------------------------------
`crm/routes.py:290` requires one, and the argument there is explicit about WHY: running
the assistant COSTS MONEY, so a repeat has to be answered rather than re-run. Neither half
transfers. A repeated acceptance spends nothing, calls no vendor, and changes no answer
this system gives — the ledger is append-only, `latest_acceptances` reads the newest row,
and two identical rows resolve to the same verdict as one. What a duplicate costs is one
row and one audit entry, which is a truthful record of two clicks rather than a defect;
suppressing the second would make the ledger claim the owner clicked once when they
clicked twice. And the header is not free: `crm` documents that an OPTIONAL key protects
only the callers that remember to send one, so the honest choices are "required" or
"absent", and requiring one here would put a 400 in front of a curl request that is
correct. Absent, deliberately, recorded here because the neighbouring route's rule is
loud enough that its absence needs a reason.

There is no DELETE and no withdrawal. `legal/models.py` argues it: this is contract
formation, not consent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta, role_has
from apps.api.legal import catalogue, readiness, statements
from apps.api.legal import service as legal_service

router = APIRouter(prefix="/v1/legal", tags=["legal"])

Session = Annotated[AsyncSession, Depends(db)]
# NO `realm=` ON THE READ, and that is the whole point of choosing `org:read` for it.
# `requires(..., realm="client")` refuses a request carrying `X-Impersonate-Org` OUTRIGHT
# (`core/auth.current_principal`), before any permission is considered — so declaring the
# read that way would make this screen unreachable from a view-as session no matter which
# permission it asked for, which is the D-22 mistake stated three paragraphs up, made in
# the module that states it. The house shape for a client-realm READ is the bare
# `requires("org:read")` (`compliance/kyc_routes.KycReader` is the neighbouring instance),
# and the `principal.impersonating` arm in `read_readiness` is live only under it.
Reader = Annotated[Principal, Depends(requires("org:read"))]
Owner = Annotated[Principal, Depends(requires("org:manage", realm="client"))]

#: The five states one document can be in, spelled as a `Literal` so the generated
#: TypeScript is a union a screen can exhaustively switch on — the device
#: `KYC_STATUS_COPY` uses to stop compiling when the API adds a state nobody wrote copy
#: for. `not_required` is the four readable documents: published, linked, never accepted.
DocumentState = Literal[
    "accepted", "never_accepted", "reacceptance_required", "changed", "not_required"
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LegalDocumentOut(Strict):
    """One published document and where this organisation stands with it."""

    slug: str
    title: str
    #: Where to READ it. Absolute path rather than a slug the console re-assembles: the
    #: page already exists at `/legal/<slug>` and one spelling of that route means a
    #: renamed segment cannot leave the accept button pointing at a 404.
    href: str
    #: Does an unaccepted copy stop this organisation operating?
    blocking: bool
    version: str
    #: Was this version published before legal review? True for everything today.
    provisional: bool
    #: ISO-8601, or null while the document has no effective date — which is the case for
    #: all eight, because `{{EFFECTIVE_DATE}}` is still a blank in the bundle. Null is a
    #: fact the screen states, not a field it hides.
    effective_date: str | None
    state: DocumentState
    #: The state in a sentence, server-authored. The console prints it and composes none.
    headline: str
    accepted_version: str | None
    accepted_at: datetime | None
    #: WHO accepted, for the screen that has to show a colleague's signature. A display
    #: name, never an email address: the name answers "who", and an address on a screen is
    #: one more copy of a contact detail nothing here needs.
    accepted_by_name: str | None


class ReadinessRowOut(Strict):
    """One thing standing in the way, and whose move it is."""

    rule: str
    title: str
    reason: str
    actor: Literal["client", "calevate"]
    next_step: str


class LegalReadinessOut(Strict):
    """The whole screen in one read."""

    #: THE VERDICT, computed by the server from the same predicates the gates use.
    may_operate: bool
    #: What that verdict means, in the client's words.
    verdict: str
    #: How many BLOCKING documents still need accepting. Feeds the nav badge; the console
    #: must not count the list itself, or an added document would need two edits.
    outstanding_documents: int
    #: Are the published documents still pre-legal-review?
    pending_legal_review: bool
    #: The paragraph above the documents while that is true, or null once it is not.
    provisional_notice: str | None
    #: The exact wording the owner agrees to, and the version a stored row records. NO
    #: DEFAULTS: a Pydantic field with a default is OPTIONAL in the generated TypeScript,
    #: and a console that must render the text somebody is agreeing to cannot be handed a
    #: `| null` for it.
    acceptance_statement: str
    acceptance_statement_version: str
    #: May THIS caller accept? Answered by the server so the screen never has to reason
    #: about roles, and so a reader who cannot accept is told why instead of shown a
    #: button that 403s.
    can_accept: bool
    can_accept_reason: str | None
    documents: list[LegalDocumentOut]
    blockers: list[ReadinessRowOut]


class AcceptIn(Strict):
    """What the owner is accepting, echoed back so a stale tab is refused rather than
    recorded. Both fields are the SERVER's own strings from the read above — the browser
    mints neither, exactly as it mints no amount on the AI-extra purchase."""

    slug: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=64)
    statement_version: str = Field(min_length=1, max_length=64)


def _headline(
    spec: catalogue.LegalDocumentSpec, accepted: legal_service.Acceptance | None
) -> tuple[str, DocumentState]:
    """The state of one document and the sentence for it — ONE function, so the word and
    the wording can never disagree."""
    version = accepted.document_version if accepted is not None else None
    if not spec.blocking:
        return (
            "Published for you to read. There is nothing to accept.",
            "not_required",
        )
    if accepted is None:
        return ("Not accepted yet.", "never_accepted")
    if catalogue.reacceptance_required(spec, version):
        return (
            "This document has changed in a way that needs accepting again.",
            "reacceptance_required",
        )
    if catalogue.changed_since(spec, version):
        return (
            "Updated since you accepted it. The change does not affect what you agreed "
            "to, so nothing is blocked — read it when convenient and confirm.",
            "changed",
        )
    return ("Accepted.", "accepted")


def _document_out(
    spec: catalogue.LegalDocumentSpec, accepted: legal_service.Acceptance | None
) -> LegalDocumentOut:
    headline, state = _headline(spec, accepted)
    return LegalDocumentOut(
        slug=spec.slug,
        title=spec.title,
        href=f"/legal/{spec.slug}",
        blocking=spec.blocking,
        version=spec.current_version,
        provisional=catalogue.is_provisional(spec.current_version),
        effective_date=spec.effective_date,
        state=state,
        headline=headline,
        accepted_version=accepted.document_version if accepted else None,
        accepted_at=accepted.accepted_at if accepted else None,
        accepted_by_name=accepted.accepted_by_name if accepted else None,
    )


def _verdict(may_operate: bool, outstanding: int) -> str:
    """One sentence for the top of the screen.

    The outstanding-agreements case gets its own wording rather than the generic one,
    because it is the only item on this screen the reader can clear in the next thirty
    seconds without leaving the page.
    """
    if may_operate:
        return "Nothing is holding up your outgoing calls."
    if outstanding:
        return (
            "Your agreements have not been accepted, so this account cannot make "
            "outgoing calls or publish an agent yet."
        )
    return (
        "This account cannot make outgoing calls yet. What is in the way is listed "
        "below, with whose move each one is. Calls coming in are unaffected."
    )


@router.get(
    "/readiness",
    response_model=LegalReadinessOut,
    openapi_extra=permission_meta("org:read"),
    summary="Agreements and everything else standing between this account and operating",
    description=(
        "The published documents with this account's acceptance state, every "
        "organisation-level condition currently blocking outgoing calls, and whether the "
        "account may operate. Every verdict and every sentence is decided server-side."
    ),
)
async def read_readiness(session: Session, principal: Reader) -> LegalReadinessOut:
    assert principal.tenant_id is not None
    accepted = await legal_service.latest_acceptances(session, tenant_id=principal.tenant_id)
    rows = await readiness.readiness_rows(session, tenant_id=principal.tenant_id)
    outstanding = legal_service.outstanding_slugs(accepted)

    # WHY THE PERMISSION IS READ OFF THE PRINCIPAL RATHER THAN GUESSED FROM THE ROLE:
    # `role_has` is the same predicate `requires("org:manage")` will apply to the POST, so
    # the button's enabled state and the endpoint's answer come from one rule. An
    # impersonating operator holds the permission and is still refused by D-22, which is
    # why that arm is asked separately and first — it is the commoner case on this screen.
    if principal.impersonating:
        can_accept, reason = (
            False,
            "You are viewing this account read-only, so you cannot accept its agreements. "
            "Only the account owner can, from their own console.",
        )
    elif principal.role is None or not role_has(principal.role, "org:manage"):
        can_accept, reason = (
            False,
            "Only the account owner can accept these agreements. You can read every "
            "document here, and everything outstanding is listed below.",
        )
    else:
        can_accept, reason = True, None

    return LegalReadinessOut(
        may_operate=not rows,
        verdict=_verdict(not rows, len(outstanding)),
        outstanding_documents=len(outstanding),
        pending_legal_review=catalogue.PENDING_LEGAL_REVIEW,
        provisional_notice=(
            statements.PROVISIONAL_NOTICE if catalogue.PENDING_LEGAL_REVIEW else None
        ),
        acceptance_statement=statements.statement_text(),
        acceptance_statement_version=statements.statement_version(),
        can_accept=can_accept,
        can_accept_reason=reason,
        documents=[_document_out(spec, accepted.get(spec.slug)) for spec in catalogue.DOCUMENTS],
        blockers=[
            ReadinessRowOut(
                rule=row.rule,
                title=row.title,
                reason=row.reason,
                actor=row.actor,
                next_step=row.next_step,
            )
            for row in rows
        ],
    )


@router.post(
    "/acceptances",
    response_model=LegalReadinessOut,
    status_code=201,
    openapi_extra=permission_meta("org:manage"),
    summary="Accept one agreement, at the version currently published (append-only)",
    description=(
        "Appends one row to the acceptance ledger and one entry to the audit log, in the "
        "same transaction. Only the account owner can accept, and an impersonated "
        "session cannot. A version or an acceptance wording that is no longer current is "
        "refused rather than recorded."
    ),
)
async def accept(
    payload: AcceptIn,
    session: Session,
    request: Request,
    principal: Owner,
) -> LegalReadinessOut:
    assert principal.tenant_id is not None
    if principal.user_id is None:
        # Unreachable through `requires(..., realm="client")`, which resolves a
        # membership — but the type says `UUID | None`, and an acceptance attributed to
        # nobody is the one thing this ledger must never contain.
        raise ProblemError.forbidden("An agreement can only be accepted by a named person.")

    acceptance = await legal_service.record_acceptance(
        session,
        tenant_id=principal.tenant_id,
        slug=payload.slug,
        version=payload.version,
        statement_version=payload.statement_version,
        user_id=principal.user_id,
    )
    await write_audit(
        session,
        action="legal.agreement_accepted",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="legal_acceptances",
        object_id=acceptance.document_slug,
        # THE CALLER'S ADDRESS IS RECORDED HERE AND NOWHERE ELSE. The ledger row carries
        # no `ip` column on purpose (`legal/models.py` argues it): this entry is written
        # in the same transaction, names the same act, and lives in the hash-chained log.
        ip=client_request_ip(request),
        summary={
            "document_slug": acceptance.document_slug,
            "document_version": acceptance.document_version,
            "statement_version": acceptance.statement_version,
            "provisional": catalogue.is_provisional(acceptance.document_version),
        },
    )
    # The WHOLE screen back, not an acknowledgement: accepting the third of four
    # agreements changes `may_operate`, the blocker list and the nav badge, and a console
    # that had to re-read to find out would show a stale verdict for one round trip on the
    # one screen whose subject is whether the account may operate.
    return await read_readiness(session, principal)


__all__ = ["router"]
