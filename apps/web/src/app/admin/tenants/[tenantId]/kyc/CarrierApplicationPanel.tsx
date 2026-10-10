"use client";

import { Section } from "@/components/console/section";
import { useState } from "react";
import { AlertTriangle, CheckCircle2 } from "lucide-react";

import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { useAdminAccess } from "@/app/admin/access";
import { useRecordCarrierDecision, useTenantCarrierApplication } from "@/lib/api/admin";
import {
  CARRIER_DECISIONS,
  CARRIER_STATUS_COPY,
  asCarrierStatus,
  carrierDecisionBlockReason,
  carrierStatusLabel,
  type CarrierApplication,
  type CarrierDecision,
  type CarrierDecisionIn,
} from "@/lib/api/kyc";

import { StatusPill } from "@/components/admin/kit";
import { FactList, SubHeading } from "./FactList";

/**
 * The header's one-glance carrier state. `is_accepted` is the SERVER's predicate, printed
 * and never recomputed: the purchase gate and this pill must not be able to disagree about
 * whether a state is good enough for a number.
 */
export function CarrierPill({ application }: { application: CarrierApplication }) {
  // The current carrier needs no per-client application (Vobiz, D-666), so no gate reads it.
  if (!application.required) return <StatusPill tone="neutral">Carrier: not required</StatusPill>;
  if (!application.recorded) return <StatusPill tone="neutral">Carrier: nothing sent</StatusPill>;
  const status = asCarrierStatus(application.status);
  const tone = application.is_accepted ? "ok" : status ? CARRIER_STATUS_COPY[status].tone : "warn";
  return (
    <StatusPill tone={tone}>
      Carrier: {carrierStatusLabel(application.status) ?? "unknown"} ·{" "}
      {application.is_accepted ? "numbers open" : "numbers closed"}
    </StatusPill>
  );
}

/**
 * The CARRIER's decision about this client — the other half of the number gate, on the
 * same screen as ours because the two records answer one question ("may this business
 * have a phone connection?") with two authorities, and an operator who cleared one would
 * otherwise walk away believing the gate was open. `assert_carrier_application_accepted`
 * refuses a number purchase on anything but `accepted`.
 *
 * No typed confirmation, deliberately: `record_decision` takes no `X-Confirm-Action`, the
 * write is a CAS over an audited state machine, and every state has a way back (an
 * acceptance recorded in error is corrected by recording `expired`). Ceremony on a
 * reversible act teaches operators to type past ceremony.
 */
export function CarrierApplicationPanel({
  tenantId,
  application,
}: {
  tenantId: string;
  /**
   * The screen's read, passed down rather than read again: every read of this route
   * writes an audit row, and the header pill needs the same answer.
   */
  application: ReturnType<typeof useTenantCarrierApplication>;
}) {
  const record = useRecordCarrierDecision(tenantId);
  const write = useAdminAccess("admin:tenants", "record a carrier decision");

  return (
    <Section
      title="Carrier's decision"
      info={
        <p>
          Our telephony carrier approves each client business separately. Their answer
          reaches us out of band — by email or in their console — and this is where it is
          recorded. Recording it asks the carrier nothing; it is written to an append-only
          audit trail with your name on it, and the client sees it on their verification
          screen.
        </p>
      }
    >
      <p className="-mt-1 text-body text-ink-muted">
        {application.data && !application.data.required
          ? "The current carrier does not approve client businesses separately, so nothing here gates this client's numbers or calls. A decision recorded here applies only if the carrier is switched back to Plivo."
          : "Until it says accepted, no number can be provisioned for this client however their identity verification above stands."}
      </p>

      <div className="mt-4 space-y-5">
        {application.error && (
          <ProblemNotice error={application.error} onRetry={() => application.refetch()} />
        )}

        {application.isLoading ? (
          <Skeleton rows={4} />
        ) : !application.data ? (
          /* Withheld, not merely unpopulated: a decision is a CAS against the state on
             file, so recording one blind means guessing which decision is even legal. */
          <NoticeBox
            tone="warn"
            icon={<AlertTriangle className="h-5 w-5" />}
            title="Cannot record a decision while the application is unreadable"
          >
            <p className="mt-1 text-meta opacity-90">
              We could not read what the carrier has on file for this client. Retry the read
              above; the form comes back with it.
            </p>
          </NoticeBox>
        ) : (
          <>
            <OnFile application={application.data} />
            <div>
              <SubHeading>Record the carrier&apos;s decision</SubHeading>
              <DecisionForm
                key={stamp(application.data)}
                application={application.data}
                record={record}
                write={write}
              />
            </div>
            {record.error != null && <ProblemNotice error={record.error} />}
            {record.data && (
              <NoticeBox tone="ok" icon={<CheckCircle2 className="h-5 w-5" />}>
                <p>
                  {record.data.changed
                    ? `Recorded as ${carrierStatusLabel(record.data.status)}.`
                    : `This application was already ${carrierStatusLabel(record.data.status)}, so nothing moved.`}{" "}
                  The panel above has re-read what is now stored.
                </p>
              </NoticeBox>
            )}
          </>
        )}
      </div>
    </Section>
  );
}

/** Content, not identity: an equal refetch must not wipe a half-typed form. */
function stamp(application: CarrierApplication): string {
  return [
    application.recorded,
    application.status,
    application.carrier_application_id,
    application.rejection_reason,
    application.decided_at,
  ].join("|");
}

/** What the carrier has on file right now, read from the server and never echoed. */
function OnFile({ application }: { application: CarrierApplication }) {
  if (!application.recorded) {
    return (
      <div>
        <SubHeading>Nothing sent to the carrier yet</SubHeading>
        <p className="text-body text-ink-muted">
          The normal state of a new account, and not something this screen can move: the
          client uploads their own registration documents from their verification screen,
          because only they hold them. There is nothing to record until they have.
        </p>
      </div>
    );
  }

  const status = asCarrierStatus(application.status);
  const copy = status ? CARRIER_STATUS_COPY[status] : null;

  return (
    <div>
      <SubHeading>Application on file</SubHeading>
      <p className="mb-3 text-body text-ink-muted">
        {copy
          ? copy.meaning
          : /* FAIL VISIBLE: a state this build has no word for is the one worth reading,
               printed as sent, never quietly treated as one we know. */
            `“${application.status}”. This build has no description for that state. It is printed exactly as the API sent it; tell engineering, and record a decision below only if one of the four clearly matches what the carrier said.`}
      </p>
      <FactList
        rows={[
          { label: "Carrier", value: application.carrier },
          { label: "Their application reference", value: application.carrier_application_id },
          { label: "Document sent", value: application.document_kind },
          { label: "File", value: application.document_filename },
          {
            label: "Signed application form",
            value: application.signed_application_on_file ? "On file" : "Not on file",
          },
          { label: "Carrier's reason", value: application.rejection_reason },
          {
            label: "Sent to carrier",
            value: application.submitted_at ? formatIST(application.submitted_at) : null,
          },
          {
            label: "Decision recorded",
            value: application.decided_at ? formatIST(application.decided_at) : null,
          },
        ]}
      />
    </div>
  );
}

const DECISIONS = Object.keys(CARRIER_DECISIONS) as CarrierDecision[];

/**
 * The decision is chosen first and the field it must name appears with it: an acceptance
 * needs the carrier's reference (a number purchase quotes it), a rejection needs their
 * reason (the client is shown it and is the only one who can act on it). Both are refused
 * again by the route and by a CHECK constraint underneath it.
 */
function DecisionForm({
  application,
  record,
  write,
}: {
  application: CarrierApplication;
  record: ReturnType<typeof useRecordCarrierDecision>;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const [decision, setDecision] = useState<CarrierDecision>("accepted");
  const [body, setBody] = useState<CarrierDecisionIn>({
    carrier_application_id: application.carrier_application_id ?? "",
    rejection_reason: "",
  });

  const set = <K extends keyof CarrierDecisionIn>(key: K, value: CarrierDecisionIn[K]) => {
    setBody((prev) => ({ ...prev, [key]: value }));
    record.reset();
  };

  const blocked = carrierDecisionBlockReason(application, decision, body);
  const spec = CARRIER_DECISIONS[decision];

  return (
    <form
      className="max-w-xl space-y-4"
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        if (blocked) return;
        record.mutate({ decision, body });
      }}
    >
      <RestrictionNote reason={write.reason} />

      <div>
        <label htmlFor="carrier-decision" className={FIELD_LABEL}>
          What the carrier decided
        </label>
        <select
          id="carrier-decision"
          value={decision}
          disabled={!write.allowed}
          onChange={(e) => {
            setDecision(e.target.value as CarrierDecision);
            record.reset();
          }}
          aria-describedby="carrier-decision-hint"
          className={FIELD}
        >
          {DECISIONS.map((value) => (
            <option key={value} value={value}>
              {CARRIER_DECISIONS[value].label}
            </option>
          ))}
        </select>
        <span id="carrier-decision-hint" className={FIELD_HINT}>
          {spec.effect}
        </span>
      </div>

      {decision === "accepted" && (
        <div>
          <label htmlFor="carrier-reference" className={FIELD_LABEL}>
            Carrier&apos;s application reference
          </label>
          <input
            id="carrier-reference"
            type="text"
            maxLength={200}
            value={body.carrier_application_id ?? ""}
            disabled={!write.allowed}
            onChange={(e) => set("carrier_application_id", e.target.value)}
            aria-describedby="carrier-reference-hint"
            className={`${FIELD} font-mono`}
          />
          <span id="carrier-reference-hint" className={FIELD_HINT}>
            Copy it from the carrier&apos;s console exactly as printed. Every number purchase
            for this client quotes it.
          </span>
        </div>
      )}

      {decision === "rejected" && (
        <div>
          <label htmlFor="carrier-reason" className={FIELD_LABEL}>
            Why the carrier refused it
          </label>
          <textarea
            id="carrier-reason"
            rows={3}
            maxLength={2000}
            value={body.rejection_reason ?? ""}
            disabled={!write.allowed}
            onChange={(e) => set("rejection_reason", e.target.value)}
            aria-describedby="carrier-reason-hint"
            className={FIELD}
          />
          <span id="carrier-reason-hint" className={FIELD_HINT}>
            Shown to the client on their own screen, so write it as something they can act on
            — which document was wrong, and what to send instead.
          </span>
        </div>
      )}

      {blocked && (
        <NoticeBox tone="warn" icon={<AlertTriangle className="h-5 w-5" />}>
          <p>{blocked}</p>
        </NoticeBox>
      )}

      <button
        type="submit"
        className={`${PRIMARY_BUTTON} max-sm:w-full max-sm:justify-center`}
        disabled={!write.allowed || blocked !== null || record.isPending}
      >
        {record.isPending ? "Recording…" : "Record decision"}
      </button>
    </form>
  );
}
