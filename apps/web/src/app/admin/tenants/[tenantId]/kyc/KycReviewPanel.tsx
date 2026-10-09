"use client";

import { useState } from "react";

import { Card, FIELD, FIELD_HINT, FIELD_LABEL, NoticeBox, PRIMARY_BUTTON, ProblemNotice, SECONDARY_BUTTON, formatIST } from "@/components/ui";
import type { AdminAccess } from "@/app/admin/access";
import { lookup } from "@/lib/lookup";
import {
  KycViewerBlockedError,
  openKycDocument,
  useAdminTenantKyc,
  useReviewKyc,
  useSetDigiLockerRequirement,
  type AdminKyc,
} from "@/lib/api/kycReview";

const ID_TYPE_LABEL: Record<string, string> = { aadhaar: "Aadhaar", pan: "PAN" };
const KIND_LABEL: Record<string, string> = {
  gst: "GST certificate",
  incorporation: "Certificate of Incorporation",
  udyam: "Udyam certificate",
  aadhaar: "Aadhaar copy (no longer accepted)",
  pan_card: "PAN card",
};

/** The Income Tax Department's free "Verify Your PAN" service (D-696). */
export const VERIFY_PAN_URL = "https://eportal.incometax.gov.in/iec/foservices/#/pre-login/verifyYourPAN";

/**
 * D-692 review: the client's declared details, the files on record, approve or reject, and
 * "require DigiLocker". A document review is approved only after the reviewer has matched the
 * PAN, name and date of birth at Income Tax and ticked that it matched (D-696). The owner's ID file is deleted by the server the moment a decision
 * is recorded, so the reviewer opens it before deciding.
 */
export function KycReviewPanel({ tenantId, access }: { tenantId: string; access: AdminAccess }) {
  const kyc = useAdminTenantKyc(tenantId);
  if (kyc.error) return <ProblemNotice error={kyc.error} onRetry={() => void kyc.refetch()} />;
  if (!kyc.data) return null;
  return (
    <div className="space-y-5">
      <ReviewCard tenantId={tenantId} record={kyc.data} access={access} />
      <DigiLockerCard tenantId={tenantId} record={kyc.data} access={access} />
    </div>
  );
}

function ReviewCard({ tenantId, record, access }: { tenantId: string; record: AdminKyc; access: AdminAccess }) {
  const review = useReviewKyc(tenantId);
  const [documentRef, setDocumentRef] = useState("");
  const [reason, setReason] = useState("");
  const [panChecked, setPanChecked] = useState(false);
  const [opening, setOpening] = useState<string | null>(null);
  const [openError, setOpenError] = useState<unknown>(null);
  const waiting = record.status === "submitted" || record.status === "in_review";
  const business = record.documents.find((document) => document.slot === "business");
  const documentReview = record.kyc_path === "manual";

  return (
    <Card title="Verification review">
      <dl className="grid gap-2 text-sm sm:grid-cols-2">
        <Fact label="Status" value={record.status ?? "nothing on file"} />
        <Fact label="Path" value={record.kyc_path === "digilocker" ? "DigiLocker" : record.kyc_path === "manual" ? "Document review" : "—"} />
        <Fact label="Legal name" value={record.legal_business_name ?? "—"} />
        <Fact label="GST" value={record.gst_registered === null ? "—" : record.gst_registered ? `Yes, ${record.gstin ?? ""}` : "No"} />
        <Fact label="Owner" value={record.owner_name ?? "—"} />
        <Fact
          label="Owner ID"
          value={record.owner_id_type ? `${lookup(ID_TYPE_LABEL, record.owner_id_type) ?? record.owner_id_type} ${record.owner_id_masked ?? ""}` : "—"}
        />
        {record.owner_pan_checked && (
          <Fact
            label="PAN check"
            value={[
              "PAN details matched at Income Tax",
              record.owner_pan_checked_by && `checked by ${record.owner_pan_checked_by}`,
              record.owner_pan_checked_at && `on ${formatIST(record.owner_pan_checked_at)}`,
            ]
              .filter(Boolean)
              .join(", ")}
          />
        )}
        {record.verified_name && (
          <Fact
            label="DigiLocker name"
            value={`${record.verified_name}${record.name_match === false ? " — does not match the owner" : record.name_match ? " — matches" : ""}`}
          />
        )}
        <Fact
          label="Pledge"
          value={
            record.pledge_accepted_version === null
              ? "Not accepted"
              : record.pledge_accepted_version === record.pledge_current_version
                ? `Accepted (version ${record.pledge_accepted_version})`
                : `Outdated (version ${record.pledge_accepted_version} of ${record.pledge_current_version})`
          }
        />
      </dl>

      <h3 className="mt-4 text-sm font-semibold text-ink">Files</h3>
      {record.documents.length === 0 ? (
        <p className="text-sm text-ink-muted">No files on record.</p>
      ) : (
        <ul className="mt-1 space-y-1 text-sm">
          {record.documents.map((document) => (
            <li key={document.id} className="flex flex-wrap items-center gap-2">
              <span>{lookup(KIND_LABEL, document.kind) ?? document.kind}</span>
              {document.held ? (
                <button
                  type="button"
                  className={SECONDARY_BUTTON}
                  disabled={opening === document.id}
                  onClick={() => {
                    setOpening(document.id);
                    setOpenError(null);
                    openKycDocument(tenantId, document.id)
                      .catch((error: unknown) => setOpenError(error))
                      .finally(() => setOpening(null));
                  }}
                >
                  Open
                </button>
              ) : (
                <span className="text-ink-muted">deleted after review</span>
              )}
            </li>
          ))}
        </ul>
      )}
      {openError instanceof KycViewerBlockedError ? (
        <p role="alert" className="mt-2 text-sm text-danger">
          {openError.message}
        </p>
      ) : (
        <ProblemNotice error={openError} />
      )}

      {waiting && (
        <div className="mt-4 space-y-3">
          {documentReview && (
            <NoticeBox tone="neutral" title="Check the PAN at Income Tax before approving">
              <ol className="mt-1 list-decimal space-y-1 pl-5">
                <li>Open the PAN card file and read the PAN, the full name and the date of birth.</li>
                <li>
                  Enter them at{" "}
                  <a href={VERIFY_PAN_URL} target="_blank" rel="noopener noreferrer" className="underline">
                    Income Tax: Verify Your PAN
                  </a>{" "}
                  with your own mobile number, and type the OTP it sends. One mobile can check at most 5 PANs a day.
                </li>
                <li>Approve only if it says the details match. If they do not, reject and say which detail differs.</li>
              </ol>
              <p className="mt-1">We store only that the details matched, who checked and when; never the date of birth.</p>
            </NoticeBox>
          )}
          {business && business.kind !== "gst" && (
            <label className="block">
              <span className={FIELD_LABEL}>Registry number checked (CIN, LLPIN or Udyam)</span>
              <input className={FIELD} value={documentRef} onChange={(event) => setDocumentRef(event.target.value)} />
            </label>
          )}
          {documentReview && (
            <label className="flex items-start gap-2 text-sm text-ink">
              <input
                type="checkbox"
                className="mt-1"
                checked={panChecked}
                onChange={(event) => setPanChecked(event.target.checked)}
              />
              <span>PAN details matched at Income Tax (PAN, full name and date of birth)</span>
            </label>
          )}
          <label className="block">
            <span className={FIELD_LABEL}>Reason (required to reject; shown to the client)</span>
            <textarea className={FIELD} value={reason} onChange={(event) => setReason(event.target.value)} rows={2} />
          </label>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className={PRIMARY_BUTTON}
              disabled={!access.allowed || review.isPending || (documentReview && !panChecked)}
              onClick={() =>
                review.mutate({
                  decision: "approve",
                  document_ref: documentRef.trim() || null,
                  reason: null,
                  pan_checked: documentReview && panChecked,
                })
              }
            >
              Approve
            </button>
            <button
              type="button"
              className={SECONDARY_BUTTON}
              disabled={!access.allowed || review.isPending || !reason.trim()}
              onClick={() => review.mutate({ decision: "reject", document_ref: null, reason: reason.trim(), pan_checked: false })}
            >
              Reject
            </button>
          </div>
          <p className={FIELD_HINT}>Either decision deletes the owner&apos;s ID file.</p>
          {access.reason && <p className="text-sm text-ink-muted">{access.reason}</p>}
          <ProblemNotice error={review.error} />
        </div>
      )}
    </Card>
  );
}

function DigiLockerCard({ tenantId, record, access }: { tenantId: string; record: AdminKyc; access: AdminAccess }) {
  const set = useSetDigiLockerRequirement(tenantId);
  const [reason, setReason] = useState("");
  return (
    <Card title="Require DigiLocker">
      <p className="text-sm text-ink">
        Requiring DigiLocker pauses this client&apos;s OUTGOING calls until they complete a DigiLocker verification;
        incoming calls are not affected.
      </p>
      {record.digilocker_required ? (
        <div className="mt-3 space-y-2">
          <p className="text-sm text-ink">
            Required{record.digilocker_required_reason ? `: ${record.digilocker_required_reason}` : ""}.{" "}
            {record.digilocker_outstanding ? "Not completed yet — outbound is paused." : "Completed."}
          </p>
          <button
            type="button"
            className={SECONDARY_BUTTON}
            disabled={!access.allowed || set.isPending}
            onClick={() => set.mutate({ required: false, reason: null })}
          >
            Stop requiring DigiLocker
          </button>
        </div>
      ) : (
        <div className="mt-3 space-y-2">
          <label className="block">
            <span className={FIELD_LABEL}>Why (recorded)</span>
            <input className={FIELD} value={reason} onChange={(event) => setReason(event.target.value)} maxLength={500} />
          </label>
          <button
            type="button"
            className={PRIMARY_BUTTON}
            disabled={!access.allowed || set.isPending || !reason.trim()}
            onClick={() => set.mutate({ required: true, reason: reason.trim() })}
          >
            Require DigiLocker
          </button>
        </div>
      )}
      <ProblemNotice error={set.error} />
    </Card>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs font-medium text-ink-muted">{label}</dt>
      <dd className="text-ink">{value}</dd>
    </div>
  );
}
