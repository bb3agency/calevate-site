"use client";

import { AlertTriangle, CheckCircle2 } from "lucide-react";

import { Card, NoticeBox, ProblemNotice, Skeleton, formatIST } from "@/components/ui";
import { PageHeader } from "@/components/console/pageHeader";
import { useAdminAccess } from "@/app/admin/access";
import { Term } from "@/lib/glossary";
import {
  useRecordKyc,
  useTenant,
  useTenantCarrierApplication,
  useTenantKyc,
} from "@/lib/api/admin";
import {
  KYC_STATUS_COPY,
  documentKindLabel,
  entityTypeLabel,
  isKnownKycStatus,
  type KycRecord,
} from "@/lib/api/kyc";

import { TonePill } from "../tonePill";
import { CarrierApplicationPanel, CarrierPill } from "./CarrierApplicationPanel";
import { FactList, SubHeading } from "./FactList";
import { KycRecordForm } from "./KycRecordForm";
import { KycReviewPanel } from "./KycReviewPanel";
import { recordStamp } from "./kycDraft";

/**
 * Recording a business's identity verification and the carrier's decision — the two
 * records behind "may this business have a phone connection?".
 *
 * A verification gets nobody a number: the client takes the connection in their own name
 * on their own Exotel / Plivo / Vobiz account and stays the subscriber of record (Model B,
 * `docs/legal/LEGAL-OPS-PLAYBOOK.md` §9). This record exists because their operator
 * verifies the same entity we do, and our dial gate must not be looser than the carrier's.
 *
 * Read through impersonation, written through the admin surface (D-22): there is no
 * admin-realm read of a tenant's KYC, because `org:read` keeps it visible in a read-only
 * session, and the write is `admin:tenants` with the tenant in the PATH.
 */
export function KycScreen({ tenantId }: { tenantId: string }) {
  const tenant = useTenant(tenantId).data;
  const slug = tenant?.slug ?? "";
  // Held here, not in the form: a successful write remounts the form by its key, and a
  // mutation held inside it would take the confirmation of the write down with it.
  const save = useRecordKyc(tenantId);
  const record = useTenantKyc(slug);
  // One read for the header pill and the panel: each read of this route is audited.
  const application = useTenantCarrierApplication(tenantId);
  const write = useAdminAccess("admin:tenants", "record an identity verification");

  // The tenant layout resolves this before mounting the page.
  if (!tenant) return null;

  return (
    <div className="space-y-5">
      <PageHeader
        title={
          <>
            Identity verification (<Term id="kyc" audience="operator" />)
          </>
        }
        status={
          <>
            {record.data && <OurPill record={record.data} />}
            {application.data && <CarrierPill application={application.data} />}
          </>
        }
        description="Our identity check and the carrier's approval. Both gate a phone number."
      />

      <KycReviewPanel tenantId={tenantId} access={write} />

      <Card
        title="Our identity check"
        info={
          <p>
            Saving records or updates the check — re-recording is what happens on every
            re-verification, and moving off verified clears the verification date and the
            verifier with it.
          </p>
        }
      >
        <p className="-mt-1 text-sm text-ink-muted">
          A verified record opens number provisioning on every tier and outbound dialling on
          self-serve and trial accounts; inbound answering is never gated by it.
        </p>

        <div className="mt-4 space-y-5">
          {record.error && <ProblemNotice error={record.error} onRetry={() => record.refetch()} />}

          {record.isLoading ? (
            <Skeleton rows={4} />
          ) : !record.data ? (
            /* Withheld, not merely unpopulated: `status` is assigned outright by the upsert,
               so recording while the state is unreadable is a blind write that could close
               a telecom gate nobody saw open. A retry is the cheaper failure. */
            <NoticeBox
              tone="warn"
              icon={<AlertTriangle className="h-5 w-5" />}
              title="Cannot record while the current state is unreadable"
            >
              <p className="mt-1 text-xs opacity-90">
                We could not read what is on file for this client. Recording a verification
                replaces the status outright, so doing it now could close a gate that is
                currently open without anyone seeing it happen. Retry the read above; the
                form comes back with it.
              </p>
            </NoticeBox>
          ) : (
            <>
              <OnFile record={record.data} />
              <div>
                <SubHeading>Record a verification</SubHeading>
                {/* Remounted only when the STORED record changes, so an identical refetch
                    leaves a half-typed form alone (react.dev, "you might not need an
                    effect"). */}
                <KycRecordForm
                  key={recordStamp(record.data)}
                  save={save}
                  tenantName={tenant.name}
                  record={record.data}
                  write={write}
                />
              </div>
              {save.error != null && <ProblemNotice error={save.error} />}
              {save.data && (
                <NoticeBox tone="ok" icon={<CheckCircle2 className="h-5 w-5" />}>
                  <p className="text-xs">
                    Recorded as{" "}
                    <span className="font-medium">
                      {/* `status` is a plain string on the wire, so an unnameable member
                          prints as sent rather than blanking the confirmation. */}
                      {isKnownKycStatus(save.data.status)
                        ? KYC_STATUS_COPY[save.data.status].label
                        : save.data.status}
                    </span>
                    . The record above has been re-read, and the client&apos;s own screen and
                    their dial gate reflect it from the next request.
                  </p>
                </NoticeBox>
              )}
            </>
          )}
        </div>
      </Card>

      <CarrierApplicationPanel tenantId={tenantId} application={application} />
    </div>
  );
}

/** Our verdict in a few words. `is_verified` is the server's predicate, never recomputed. */
function OurPill({ record }: { record: KycRecord }) {
  if (!record.recorded) return <TonePill tone="neutral">Our check: nothing on file</TonePill>;
  const status = record.status;
  const copy = status !== null && isKnownKycStatus(status) ? KYC_STATUS_COPY[status] : null;
  return (
    <TonePill tone={record.is_verified ? "ok" : (copy?.tone ?? "warn")}>
      Our check: {copy?.label ?? status ?? "unknown"} ·{" "}
      {record.is_verified ? "gates open" : "gates closed"}
    </TonePill>
  );
}

/**
 * What is filed right now — read from the server rather than echoed from the last write,
 * because `record_kyc` COALESCEs blank optional fields against the stored row.
 */
function OnFile({ record }: { record: KycRecord }) {
  if (!record.recorded) {
    return (
      <div>
        <SubHeading>Nothing on file</SubHeading>
        <p className="text-sm text-ink-muted">
          The normal state of a new account. This client&apos;s dial gate reads it as a
          missing verification. Their own operator will ask for the same documents before it
          issues them a connection.
        </p>
      </div>
    );
  }
  return (
    <div>
      <SubHeading>On file</SubHeading>
      <FactList
        rows={[
          { label: "Entity type", value: entityTypeLabel(record.entity_type) },
          { label: "Document", value: documentKindLabel(record.document_kind) },
          { label: "Reference", value: record.document_ref },
          { label: "Signatory", value: record.signatory_name },
          { label: "Evidence filed at", value: record.evidence_ref },
          { label: "Rejection reason", value: record.rejection_reason },
          { label: "Submitted", value: record.submitted_at ? formatIST(record.submitted_at) : null },
          { label: "Verified", value: record.verified_at ? formatIST(record.verified_at) : null },
        ]}
      />
    </div>
  );
}
