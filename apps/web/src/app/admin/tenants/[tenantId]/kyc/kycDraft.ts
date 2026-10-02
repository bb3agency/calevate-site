import {
  asDocumentKind,
  asEntityType,
  isKnownKycStatus,
  type KycRecord,
  type KycRecordIn,
} from "@/lib/api/kyc";

/** Content, not identity: an equal refetch must not wipe a half-typed form. */
export function recordStamp(record: KycRecord): string {
  return [
    record.recorded,
    record.status,
    record.entity_type,
    record.document_kind,
    record.document_ref,
    record.signatory_name,
    record.evidence_ref,
    record.rejection_reason,
  ].join("|");
}

/**
 * The form's starting point: what is filed, or a fresh record.
 *
 * Prefilled from the stored record because the endpoint upserts with COALESCE, so a blank
 * optional field leaves the filed value in place rather than clearing it. `status` falls
 * back to `submitted`, never `verified`, for a member this build does not know — a default
 * that opens the telecom gate is not a default worth having.
 */
export function initialDraft(record: KycRecord): KycRecordIn {
  const status = record.status;
  return {
    status: status !== null && isKnownKycStatus(status) ? status : "submitted",
    entity_type: asEntityType(record.entity_type),
    document_kind: asDocumentKind(record.document_kind),
    document_ref: record.document_ref,
    signatory_name: record.signatory_name,
    evidence_ref: record.evidence_ref,
    rejection_reason: record.rejection_reason,
  };
}
