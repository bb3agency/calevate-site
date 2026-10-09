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
4. **Our carrier enforces it downstream anyway.** Vobiz (D-662) requires KYC before it
   rents an Indian number, serves India-registered businesses only, and requires each
   `customer_use` sub-account to complete KYC in its own name, created with
   `kyc_calls_blocked: true` until it does. So a product that let a client "buy" a
   number without a KYC record would be writing a cheque the carrier will bounce.
   — VERIFIED-VENDOR-DOCS: `vobiz-findings/mirror/pages/compliance/india/
     calling-regulations.md:30-35` and `compliance/india/kyc.md:65`.
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
hold the CAF, or whether furnishing the entity's documents to the licensed operator behind
our carrier discharges us. The sources describe the LICENSEE's obligation
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
* **Dialling is gated for EVERY tier (D-692).** It used to be `self_serve`/`trial` only,
  on the ground that a managed client's identity was already proven by its DLT Principal
  Entity registration and gated at dial time by `pe_registration_*`. D-692 removed the
  client DLT requirement, which removed that assurance, so a verified KYC record (plus the
  no-cold-calls pledge, `compliance/outbound_pledge.py`) is now the outbound precondition
  for every account. An admin can additionally REQUIRE a DigiLocker verification for one
  client (`digilocker_outstanding`), which blocks that client's outbound until a run
  completes after the requirement was set.

**Inbound is never gated.** Nothing here is reachable from an inbound call: the gate
lives in `compliance.service.check_dispatch`, which inbound calls never enter (its
module docstring says why, and D-38 makes the receptionist the headline product). A KYC
gate that silenced a receptionist would be an outage we inflicted on ourselves, and the
caller who dialled in initiated the call anyway.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.models import KYC_VERIFIED
from apps.api.core.errors import ProblemError
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
    # WHO verified (D-635): a person at Calevate, or the client themselves through a
    # licensed aggregator. The discriminant of the widened evidence constraint, so a row
    # that cannot say is a row that cannot be `verified`.
    verification_source: str | None
    verification_provider: str | None
    # The aggregator's own transaction id for the run. This is the liability artefact —
    # a third party can be asked to corroborate it — and it is not an identity document.
    verification_reference: str | None
    # The holder name the aggregator returned. A NAME, deliberately without the number it
    # was read from, exactly as `signatory_name` is.
    verified_name: str | None
    # D-692: the path chosen, the business facts the numbering application needs, and the
    # admin's "require DigiLocker" override with the instant a run last satisfied it.
    kyc_path: str | None = None
    legal_business_name: str | None = None
    gst_registered: bool | None = None
    gstin: str | None = None
    digilocker_required: bool = False
    digilocker_required_reason: str | None = None
    digilocker_required_at: datetime | None = None
    digilocker_verified_at: datetime | None = None
    name_match: bool | None = None
    # Which owner ID proved the person (`aadhaar` | `pan`) and that ID masked.
    owner_id_type: str | None = None
    owner_id_masked: str | None = None

    @property
    def is_verified(self) -> bool:
        """The single predicate every gate asks. Computed here rather than in each
        caller so the dial gate, the launch preview, the number-purchase route and the
        client's own screen can never answer "is `in_review` good enough" differently."""
        return self.status == KYC_VERIFIED

    @property
    def digilocker_outstanding(self) -> bool:
        """An admin required DigiLocker and no run has completed SINCE they did.

        A run completed before the requirement does not satisfy it: the admin asked for a
        fresh, deeper check, and an old one is what they were looking at when they asked.
        """
        if not self.digilocker_required:
            return False
        if self.digilocker_verified_at is None or self.digilocker_required_at is None:
            return True
        return self.digilocker_verified_at < self.digilocker_required_at


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
    verification_source=None,
    verification_provider=None,
    verification_reference=None,
    verified_name=None,
)

_SELECT = (
    "SELECT status, entity_type, document_kind, document_ref, signatory_name, "
    "evidence_ref, rejection_reason, submitted_at, verified_at, "
    "verification_source, verification_provider, verification_reference, verified_name, "
    "kyc_path, legal_business_name, gst_registered, gstin, digilocker_required, "
    "digilocker_required_reason, digilocker_required_at, digilocker_verified_at, name_match, "
    "owner_id_type, owner_id_masked "
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
        verification_source=row[9],
        verification_provider=row[10],
        verification_reference=row[11],
        verified_name=row[12],
        kyc_path=row[13],
        legal_business_name=row[14],
        gst_registered=row[15],
        gstin=row[16],
        digilocker_required=bool(row[17]),
        digilocker_required_reason=row[18],
        digilocker_required_at=row[19],
        digilocker_verified_at=row[20],
        name_match=row[21],
        owner_id_type=row[22],
        owner_id_masked=row[23],
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
    verification_source: str = "operator",
    verification_provider: str | None = None,
    verification_reference: str | None = None,
    verified_name: str | None = None,
) -> None:
    """Upsert a verification. Re-recording is what happens on every re-verification.

    Two writers, one row: an operator recording a registry check (D-47) and the webhook
    absorbing an aggregator's result (D-635). `verification_source` is what tells them
    apart, it defaults to `operator` so every existing caller is unchanged, and it is the
    one field EXCLUDED wins outright on — a record re-verified by an operator must stop
    claiming a provider verified it, and the reverse.

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
        "source": verification_source,
        "provider": verification_provider,
        "reference": verification_reference,
        "verified_name": verified_name,
    }
    await session.execute(
        text(
            "INSERT INTO kyc_records (id, tenant_id, status, entity_type, document_kind, "
            "  document_ref, signatory_name, evidence_ref, rejection_reason, "
            "  verified_by_admin_id, verification_source, verification_provider, "
            "  verification_reference, verified_name, submitted_at, verified_at, "
            "  created_at, updated_at) "
            "VALUES (:id, :tid, :status, :entity_type, :document_kind, :document_ref, "
            "  :signatory_name, :evidence_ref, :rejection_reason, :admin_id, :source, "
            "  :provider, :reference, :verified_name, now(), "
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
            # The DISCRIMINANT of the evidence constraint, so EXCLUDED wins outright
            # rather than COALESCEing: a record re-verified by an operator after an
            # aggregator run must stop claiming the aggregator verified it, and the
            # reverse. The three columns below it are COALESCEd like the other evidence
            # fields, so an operator correcting a status does not erase which provider
            # confirmed the signatory and under what reference.
            "  verification_source = EXCLUDED.verification_source, "
            "  verification_provider = COALESCE(EXCLUDED.verification_provider, "
            "    kyc_records.verification_provider), "
            "  verification_reference = COALESCE(EXCLUDED.verification_reference, "
            "    kyc_records.verification_reference), "
            "  verified_name = COALESCE(EXCLUDED.verified_name, kyc_records.verified_name), "
            "  submitted_at = COALESCE(kyc_records.submitted_at, EXCLUDED.submitted_at), "
            f"  verified_at = {'now()' if verified else 'NULL'}, "
            "  updated_at = now()"
        ),
        params,
    )
    if verified:
        # A verified business may now have its details sent to its own voice workspace
        # for numbers (D-693); the job sends nothing until that workspace is active.
        # Imported here: the sender imports this module.
        from apps.api.campaigns.engine_business_details import (
            queue_business_details_submission,
        )

        await queue_business_details_submission(session, tenant_id=tenant_id)


#: The admin's "deeper verification" override (D-692), in the client's words.
DIGILOCKER_REQUIRED_REASON = (
    "We need you to verify the business owner's identity through DigiLocker before this "
    "account can place outbound calls. Open Verify your business and choose DigiLocker. "
    "Answering inbound calls is unaffected."
)

#: Statuses in which the client may still change what they declared. Once a reviewer is
#: looking at it, or it is verified, a change has to come through support — otherwise a
#: verified business could rename itself after approval.
_EDITABLE_STATUSES = (None, "not_started", "rejected", "expired")


def _tokens(name: str) -> list[str]:
    return sorted(token for token in re.split(r"[^a-z]+", name.lower()) if len(token) > 1)


def names_match(declared: str | None, attested: str | None) -> bool | None:
    """Whether the owner the client named is the person DigiLocker attested. Advisory:
    shown to the reviewer, never a gate on its own, because initials and transliteration
    make an exact rule refuse real people. None when either side is missing."""
    if not declared or not attested:
        return None
    left, right = _tokens(declared), _tokens(attested)
    if not left or not right:
        return False
    if left == right:
        return True
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    return len(shorter) >= 2 and all(token in longer for token in shorter)


async def save_business_details(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    entity_type: str,
    legal_business_name: str,
    gst_registered: bool,
    gstin: str | None,
    owner_name: str,
) -> None:
    """The client's declaration, upserted. Refused once a reviewer has it or it is verified."""
    current = await read_kyc(session, tenant_id=tenant_id)
    if current.status not in _EDITABLE_STATUSES:
        raise ProblemError.business_rule(
            "kyc_details_locked",
            "These details are with our review team or already verified, so they cannot be "
            "changed here.",
            remediation="Contact support if something needs correcting.",
        )
    # A DigiLocker run already took its branch from the entity type on file; changing it
    # afterwards would re-label a signatory check as a proprietor's.
    if current.verification_source == "aggregator" and current.entity_type != entity_type:
        raise ProblemError.business_rule(
            "entity_type_on_file_differs",
            "Our record of how this business is registered does not match what you selected.",
            remediation="Contact support to correct the registered entity type.",
        )
    await session.execute(
        text(
            "INSERT INTO kyc_records (id, tenant_id, status, entity_type, legal_business_name, "
            "  gst_registered, gstin, signatory_name, created_at, updated_at) "
            "VALUES (:id, :tid, 'not_started', :entity, :name, :gst, :gstin, :owner, now(), "
            "  now()) "
            "ON CONFLICT (tenant_id) DO UPDATE SET entity_type = EXCLUDED.entity_type, "
            "  legal_business_name = EXCLUDED.legal_business_name, "
            "  gst_registered = EXCLUDED.gst_registered, gstin = EXCLUDED.gstin, "
            "  signatory_name = EXCLUDED.signatory_name, updated_at = now()"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "entity": entity_type,
            "name": legal_business_name,
            "gst": gst_registered,
            "gstin": gstin if gst_registered else None,
            "owner": owner_name,
        },
    )


async def submit_for_manual_review(
    session: AsyncSession, *, tenant_id: UUID, owner_id_type: str, owner_id_masked: str
) -> None:
    """Move the record to `submitted` on the manual path, with the owner ID's type and
    masked number. The caller has checked that the details and both documents are on
    file."""
    await session.execute(
        text(
            "UPDATE kyc_records SET status = 'submitted', kyc_path = 'manual', "
            "  owner_id_type = :id_type, owner_id_masked = :masked, "
            "  rejection_reason = NULL, submitted_at = now(), updated_at = now() "
            "WHERE tenant_id = :tid"
        ),
        {"tid": tenant_id, "id_type": owner_id_type, "masked": owner_id_masked},
    )


async def mark_digilocker_path(session: AsyncSession, *, tenant_id: UUID) -> None:
    """Record that the client chose DigiLocker. Status is left to the outcome."""
    await session.execute(
        text(
            "UPDATE kyc_records SET kyc_path = 'digilocker', updated_at = now() "
            "WHERE tenant_id = :tid AND (kyc_path IS NULL OR status <> 'verified')"
        ),
        {"tid": tenant_id},
    )


async def record_digilocker_completion(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    verified_name: str | None,
    owner_id_type: str,
    owner_id_masked: str | None,
) -> None:
    """Stamp that a DigiLocker run completed now: which ID it fetched, that ID masked, and
    whether the attested name matches the owner the client named.

    Called for every successful run, including one on an already-verified record, because
    that is exactly how an admin's "require DigiLocker" is satisfied.
    """
    record = await read_kyc(session, tenant_id=tenant_id)
    await session.execute(
        text(
            "UPDATE kyc_records SET digilocker_verified_at = now(), name_match = :match, "
            "  owner_id_type = :id_type, "
            "  owner_id_masked = :masked, updated_at = now() "
            "WHERE tenant_id = :tid"
        ),
        {
            "tid": tenant_id,
            "match": names_match(record.signatory_name, verified_name),
            "id_type": owner_id_type,
            "masked": owner_id_masked,
        },
    )


async def set_digilocker_requirement(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    required: bool,
    reason: str | None,
    admin_id: UUID | None,
) -> None:
    """The admin override. Requiring creates the record if there is none, because an admin
    may ask for DigiLocker before the client has started anything."""
    if required:
        await session.execute(
            text(
                "INSERT INTO kyc_records (id, tenant_id, status, digilocker_required, "
                "  digilocker_required_reason, digilocker_required_at, "
                "  digilocker_required_by_admin_id, created_at, updated_at) "
                "VALUES (:id, :tid, 'not_started', true, :reason, now(), :admin, now(), now()) "
                "ON CONFLICT (tenant_id) DO UPDATE SET digilocker_required = true, "
                "  digilocker_required_reason = EXCLUDED.digilocker_required_reason, "
                "  digilocker_required_at = now(), "
                "  digilocker_required_by_admin_id = EXCLUDED.digilocker_required_by_admin_id, "
                "  updated_at = now()"
            ),
            {"id": uuid7(), "tid": tenant_id, "reason": reason, "admin": admin_id},
        )
        return
    await session.execute(
        text(
            "UPDATE kyc_records SET digilocker_required = false, "
            "  digilocker_required_reason = NULL, digilocker_required_at = NULL, "
            "  digilocker_required_by_admin_id = NULL, updated_at = now() "
            "WHERE tenant_id = :tid"
        ),
        {"tid": tenant_id},
    )


@dataclass(frozen=True, slots=True)
class NumberingSubmission:
    """What a numbering application in the client's name needs, ready to send.

    `document_kind` is the application's own vocabulary (`gst`/`incorporation`/`udyam`,
    send-business-details.md:513-522); the file is read from `object_key`. Built only from
    a VERIFIED record, so nothing is submitted in a client's name on unchecked paperwork.
    """

    tenant_id: UUID
    legal_business_name: str
    gst_registered: bool
    document_kind: str
    document_id: UUID
    object_key: str
    filename: str
    content_type: str
    size_bytes: int


async def numbering_submission_bundle(
    session: AsyncSession, *, tenant_id: UUID
) -> NumberingSubmission | None:
    """The submission-ready bundle for renting numbers in the client's own name, or None
    when the record is not verified or a field or the business document is missing."""
    from apps.api.compliance.kyc_documents import current_documents

    record = await read_kyc(session, tenant_id=tenant_id)
    if not record.is_verified or not record.legal_business_name:
        return None
    if record.gst_registered is None:
        return None
    business = (await current_documents(session, tenant_id=tenant_id)).get("business")
    if business is None or business.purged_at is not None:
        return None
    return NumberingSubmission(
        tenant_id=tenant_id,
        legal_business_name=record.legal_business_name,
        gst_registered=record.gst_registered,
        document_kind=business.kind,
        document_id=business.id,
        object_key=business.object_key,
        filename=business.filename,
        content_type=business.content_type,
        size_bytes=business.size_bytes,
    )


__all__ = [
    "DIGILOCKER_REQUIRED_REASON",
    "KYC_MISSING_REASON",
    "NOT_RECORDED",
    "KycRecord",
    "NumberingSubmission",
    "kyc_not_verified_reason",
    "mark_digilocker_path",
    "names_match",
    "numbering_submission_bundle",
    "read_kyc",
    "record_digilocker_completion",
    "record_kyc",
    "save_business_details",
    "set_digilocker_requirement",
    "submit_for_manual_review",
]
