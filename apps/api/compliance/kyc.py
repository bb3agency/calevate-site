"""Subscriber KYC — the last R-11 mitigation, and the fact the gate could not ask about.

SURFACES §2b's final self-serve bullet is "**Number purchase + KYC**: gated; calling
stays disabled until verification clears", FLOWS §2 says "self-serve accounts start
restricted (R-11): calling is gated until the org has a KYC-verified number", and BRD
§245 (⚠ its wording, "number provisioning gated behind KYC", was corrected to business
KYC by D-474 — we supply no numbers) lists it among the mitigations that ship WITH
the self-serve motion rather than after it. Nothing in the schema modelled KYC at all,
so all three sentences described a control that did not exist.

WHAT THE RESEARCH SETTLED (read before changing the shape of this record)
-------------------------------------------------------------------------
1. **A business taking a phone connection in India is KYC'd as an entity, not as a
   person.** DoT discontinued "bulk connections" and replaced them with **business
   connections** (instructions of 31 Aug 2023, expanded by further instructions in
   May 2024): to issue one, the licensee must obtain the entity's **CIN / business
   licence / trade registration**, the **customer address**, the **GST registration
   certificate where applicable**, and a **list of end-users** with name, designation
   and identity-document details. That is the document set this record refers to.
   — DMD Advocates, "Additional KYC instructions in respect of business connections";
     Medianama, "DoT released additional instructions for KYC verification of business
     connections" (May 2024).
2. **Cloud telephony is not exempt.** A DoT circular of 16 June 2025 found licensees
   providing internet telephony under the business-connection category without proper
   KYC and directed that the same KYC protocols as cellular mobile apply, with a
   90-day compliance window. A virtual number is a telecom connection.
   — Storyboard18, "DoT mandates KYC for internet telephony services using mobile
     numbers" (June 2025).
3. **The statute puts teeth on it.** Telecommunications Act 2023 **s.3(7)** obliges
   authorised entities to identify their users; fraudulently obtaining a telecom
   identifier on another person's identity carries up to three years' imprisonment and
   ₹50 lakh. This is exactly R-11's exposure — on a self-serve motion the applicant is
   a stranger — and it is why the refusals below are refusals rather than warnings.
   — The Telecommunications Act, 2023 (indiacode.nic.in), s.3.
4. **Our reseller enforces it downstream anyway.** Exotel (D-05's telephony pick)
   requires KYC plus a Customer Acquisition Form for VoIP accounts, requires the
   address proof to match the city the number is bought in, and **blocks outgoing
   calls until KYC is verified**. So a product that let a client "buy" a number
   without a KYC record would be writing a cheque the TSP will bounce.
   — Exotel support, "Where do I upload my KYC verification docs"; Exotel docs,
     "Business Phone System — Onboarding".
5. **DLT Principal Entity registration overlaps and does NOT subsume this.** PE
   registration asks for PAN, GST/CIN and the authorised signatory's government ID on
   company letterhead — the same *entity* documents — so re-collecting them would be
   waste, and this record therefore stores a REFERENCE and never a second copy. But PE
   registration is held by an access provider on a DLT portal for the purpose of
   headers and templates: it carries no address tied to the number's city, no end-user
   list, and no CAF, and no source says a registrar's PE approval discharges a
   licensee's connection KYC. Two regimes, overlapping evidence, different holders.
   — Documented DLT PE document lists (SMSCountry, Kapsystem, Infobip DLT docs).

**Not settled, and therefore not built:** whether a non-licensee reseller must itself
hold the CAF, or whether furnishing the entity's documents to the licensed operator
(Exotel's UL-VNO entity) discharges us. The sources describe the LICENSEE's obligation
and are silent on the reseller's. So this module records what we verified and where the
evidence is filed — which is useful under either answer — and does not model a CAF
document, a form workflow or a document store, none of which we can say is ours to hold.

WHO THE GATE APPLIES TO — THE MANAGED/SELF-SERVE QUESTION, ANSWERED IN TWO PARTS
--------------------------------------------------------------------------------
`plan_tier` distinguishes the two motions (D-34/D-39), and the wrong answer here either
blocks every existing client or leaves the real risk open. It is two questions, not one,
and they get different answers:

* **The number gate is asked of EVERY tier.** `provisioning.py` reads
  `read_kyc()` and tests `is_verified` with no tier test at all — it needs the whole
  record, not a boolean, because its refusal has to tell "nothing on file" apart from
  "filed and not cleared". A boolean-only `kyc_verified()` selector existed here for
  exactly one release and had no callers: the one seam it was named for could not use
  it without a second read, so it was deleted rather than kept as a second way to ask
  one question. The obligation attaches to the connection,
  and it attaches identically whether the subscriber pays us a retainer or a top-up —
  the DoT does not have a managed-client exemption. This is also what makes the gate
  un-bypassable: `plan_tier` is an admin-settable column, so a control keyed on it
  alone would be one support ticket away from being switched off, which is precisely
  the "bypass for testing" hard rule 5 forbids. It blocks no existing client because it
  can only ever refuse a *new* request, and every number a client holds was taken on
  their OWN operator account against their own KYC and CAF (Model B — `docs/legal/
  LEGAL-OPS-PLAYBOOK.md` §9). That is also why this record exists at all: we verify the
  same entity their operator verifies, so our dial gate cannot be looser than the
  carrier's.
* **Dialling is gated for `self_serve` and `trial` only.** This mirrors
  `credits_exhausted` exactly, and for the same kind of reason. FLOWS §2 and SURFACES
  §2b both scope the calling restriction to self-serve accounts, and the docs win
  (CLAUDE.md). Substantively: R-11's risk is an *anonymous* signup dialling India's
  network. A managed tenant is not anonymous — we contracted with them, an access
  provider granted their ₹5,900 Principal Entity registration only after checking
  PAN/GST/CIN and the authorised signatory's ID, and their operator issued their
  connection only against their own KYC and CAF. That assurance is out of band and
  is already gated at
  dial time by `pe_registration_*` and `number_not_registered`. Making the dial gate
  tier-blind would therefore not close a risk; it would halt every existing client's
  calling on a data-entry backlog, and this repo has already paid that price once with
  `tm_registration_missing`.

**The residual risk, stated rather than hidden:** a managed tenant whose operator KYC we
never saw keeps dialling. That gap closes at the point it can actually be
closed — an ops sweep requiring a verification for every tenant holding a number — and
that is a `platform_state`-shaped ops surface, not a change to this predicate. It is NOT
closed by widening the dial gate, which would refuse the tenants whose paperwork we do
hold along with the ones whose we do not.

**Inbound is never gated.** Nothing here is reachable from an inbound call: the gate
lives in `compliance.service.check_dispatch`, which inbound calls never enter (its
module docstring says why, and D-38 makes the receptionist the headline product). A KYC
gate that silenced a receptionist would be an outage we inflicted on ourselves, and the
caller who dialled in initiated the call anyway.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.models import KYC_VERIFIED
from apps.api.db.base import uuid7

# The client-facing wording of the two refusals, defined ONCE and shared by the dial
# gate, the campaign launch preview and the number-purchase route — the same discipline
# `SPEND_CAP_REASON` and `PE_MISSING_REASON` follow, so one condition is never explained
# three different ways on three screens.
KYC_MISSING_REASON = (
    "We have not yet verified this business's identity. Indian telecom rules require "
    "the subscriber of a phone connection to be verified before it can place calls; "
    "answering inbound calls is unaffected."
)


def kyc_not_verified_reason(status: str) -> str:
    """Names the state the record is actually in, because the next action differs.

    `submitted` means we owe them a review; `rejected` means they owe us a document;
    `expired` means the entity's paperwork lapsed. A single "not verified" string would
    send all three to the same wrong place — the mistake `pe_registration_not_active`
    already avoids by interpolating the registrar's status.
    """
    return (
        f"This business's identity verification is {status.replace('_', ' ')}; only a "
        "verified business may place outbound calls. Answering inbound calls is "
        "unaffected."
    )


@dataclass(frozen=True, slots=True)
class KycRecord:
    """What we verified about this business, for whoever is asking.

    Absence is a VALUE, not an exception: every tenant starts with no row, and a `None`
    return would push each caller into inventing the same "not filed yet" shape
    (`registration.NOT_RECORDED` makes the same argument).
    """

    # False = no row at all, the normal state of a new account, and a different fact
    # from `status='not_started'` ("we have begun and are nowhere").
    recorded: bool
    status: str | None
    entity_type: str | None
    document_kind: str | None
    document_ref: str | None
    signatory_name: str | None
    evidence_ref: str | None
    rejection_reason: str | None
    submitted_at: datetime | None
    verified_at: datetime | None

    @property
    def is_verified(self) -> bool:
        """The single predicate every gate asks. Computed here rather than in each
        caller so the dial gate, the launch preview, the number-purchase route and the
        client's own screen can never answer "is `in_review` good enough" differently."""
        return self.status == KYC_VERIFIED


NOT_RECORDED = KycRecord(
    recorded=False,
    status=None,
    entity_type=None,
    document_kind=None,
    document_ref=None,
    signatory_name=None,
    evidence_ref=None,
    rejection_reason=None,
    submitted_at=None,
    verified_at=None,
)

_SELECT = (
    "SELECT status, entity_type, document_kind, document_ref, signatory_name, "
    "evidence_ref, rejection_reason, submitted_at, verified_at "
    "FROM kyc_records WHERE tenant_id = :tid"
)


async def read_kyc(session: AsyncSession, *, tenant_id: UUID) -> KycRecord:
    """This tenant's verification, on the caller's RLS-scoped session.

    Hard rule 1: `tenant_id` is a predicate AND the session runs under RLS. The
    predicate is not the isolation — the GUC is — but a read whose predicate names the
    tenant cannot silently start returning another tenant's row if a policy is ever
    loosened; it returns zero rows twice over. A session scoped elsewhere, or one with
    no GUC at all, gets `NOT_RECORDED`, which is the correct answer in both cases: this
    session cannot see a verification, so as far as it is concerned there is none.
    """
    row = (await session.execute(text(_SELECT), {"tid": tenant_id})).first()
    if row is None:
        return NOT_RECORDED
    return KycRecord(
        recorded=True,
        status=str(row[0]),
        entity_type=row[1],
        document_kind=row[2],
        document_ref=row[3],
        signatory_name=row[4],
        evidence_ref=row[5],
        rejection_reason=row[6],
        submitted_at=row[7],
        verified_at=row[8],
    )


async def record_kyc(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    status: str,
    entity_type: str | None = None,
    document_kind: str | None = None,
    document_ref: str | None = None,
    signatory_name: str | None = None,
    evidence_ref: str | None = None,
    rejection_reason: str | None = None,
    verified_by_admin_id: UUID | None = None,
) -> None:
    """Upsert what ops verified. Re-recording is what happens on every re-verification.

    `verified_at` is stamped by the DATABASE, in the same statement, and only when the
    status is `verified` — never passed in by a caller. An operator who could supply the
    date on which a verification happened could supply any date, and the whole value of
    the column to an auditor is that it is the moment the system observed the fact
    (`dlt_registrations.verified_at` means the same thing for the same reason). Moving
    OFF `verified` clears it and the verifier along with it, so a lapsed record cannot
    keep displaying the credentials of a verification that no longer holds.

    The CHECK constraints in migration a3f6b1e02d95 are the real enforcement of "a
    verified row names its evidence"; the admin route pre-empts them so an operator gets
    a problem+json naming the missing field instead of a 500 out of an IntegrityError.
    """
    verified = status == KYC_VERIFIED
    params: dict[str, Any] = {
        "id": uuid7(),
        "tid": tenant_id,
        "status": status,
        "entity_type": entity_type,
        "document_kind": document_kind,
        "document_ref": document_ref,
        "signatory_name": signatory_name,
        "evidence_ref": evidence_ref,
        "rejection_reason": rejection_reason,
        "admin_id": verified_by_admin_id if verified else None,
    }
    await session.execute(
        text(
            "INSERT INTO kyc_records (id, tenant_id, status, entity_type, document_kind, "
            "  document_ref, signatory_name, evidence_ref, rejection_reason, "
            "  verified_by_admin_id, submitted_at, verified_at, created_at, updated_at) "
            "VALUES (:id, :tid, :status, :entity_type, :document_kind, :document_ref, "
            "  :signatory_name, :evidence_ref, :rejection_reason, :admin_id, now(), "
            f"  {'now()' if verified else 'NULL'}, now(), now()) "
            "ON CONFLICT (tenant_id) DO UPDATE SET "
            "  status = EXCLUDED.status, "
            "  entity_type = COALESCE(EXCLUDED.entity_type, kyc_records.entity_type), "
            "  document_kind = COALESCE(EXCLUDED.document_kind, kyc_records.document_kind), "
            "  document_ref = COALESCE(EXCLUDED.document_ref, kyc_records.document_ref), "
            "  signatory_name = COALESCE(EXCLUDED.signatory_name, kyc_records.signatory_name), "
            "  evidence_ref = COALESCE(EXCLUDED.evidence_ref, kyc_records.evidence_ref), "
            "  rejection_reason = EXCLUDED.rejection_reason, "
            "  verified_by_admin_id = EXCLUDED.verified_by_admin_id, "
            "  submitted_at = COALESCE(kyc_records.submitted_at, EXCLUDED.submitted_at), "
            f"  verified_at = {'now()' if verified else 'NULL'}, "
            "  updated_at = now()"
        ),
        params,
    )


__all__ = [
    "KYC_MISSING_REASON",
    "NOT_RECORDED",
    "KycRecord",
    "kyc_not_verified_reason",
    "read_kyc",
    "record_kyc",
]
