"use client";

import { useState } from "react";
import { AlertTriangle, CheckCircle2, FileWarning } from "lucide-react";

import {
  Card,
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

/**
 * The CARRIER's decision about this client — the other half of the number gate.
 *
 * ## The hole this fills
 *
 * All four carrier-application surfaces shipped together, and the two admin-realm ones
 * had no caller anywhere in this console. The consequence is the one the route's own
 * module docstring names: "a decision ops cannot record is a client stuck behind a
 * carrier that has already said yes." A business could upload its registration documents
 * from `/c/{slug}/verification`, we could forward them, the carrier could approve — and
 * the application would sit at `submitted` for ever, because nobody at Calevate had a
 * form to record the answer in and `assert_carrier_application_accepted` refuses a number
 * purchase on anything but `accepted`.
 *
 * ## Why it is on the KYC screen and not its own
 *
 * The two records answer one operator question — "may this business have a phone
 * connection?" — and they answer it with two different authorities: ours (KYC) and the
 * carrier's (this). Separating them onto two screens would mean an operator who cleared
 * one walked away believing the gate was open. They are stacked here in the order they
 * bite, with the server's own `is_accepted` predicate printed rather than re-derived.
 *
 * ## No typed confirmation, deliberately
 *
 * `record_decision` accepts no `X-Confirm-Action` and nothing here is destroyed: the
 * write is a CAS over an audited state machine, every state has a way back, and an
 * acceptance recorded in error is corrected by recording `expired`. Ceremony on a
 * reversible act is how operators learn to type past ceremony (the argument
 * `set_tenant_plan_tier` makes for carrying no step-up), and a confirmation the API
 * ignores is a confirmation of nothing (`credits.ts`).
 *
 * What DOES stand in the way is a preview of each refusal, beside the control, before
 * the round trip: which decision is legal from the state the application is in, and
 * which field that decision must name.
 */
export function CarrierApplicationPanel({ tenantId }: { tenantId: string }) {
  const application = useTenantCarrierApplication(tenantId);
  const record = useRecordCarrierDecision(tenantId);
  const write = useAdminAccess("admin:tenants", "record a carrier decision");

  return (
    <div className="space-y-3">
      <div>
        <h2 className="text-base font-semibold text-ink">Carrier compliance application</h2>
        <p className="text-sm text-ink-muted">
          Our telephony carrier approves each client business separately. Their answer
          reaches us out of band — by email or in their console — and this is where it is
          recorded. Until it says accepted, no number can be provisioned for this client
          however their identity verification above stands.
        </p>
      </div>

      {application.error && (
        <ProblemNotice error={application.error} onRetry={() => application.refetch()} />
      )}

      {application.isLoading ? (
        <Skeleton rows={4} />
      ) : !application.data ? (
        /* Withheld, not merely unpopulated — the same call the KYC form above makes. A
           decision is a CAS against the state on file, so recording one while that state
           is unreadable means guessing which decision is even legal. */
        <NoticeBox
          tone="warn"
          icon={<AlertTriangle className="h-5 w-5" />}
          title="Cannot record a decision while the application is unreadable"
        >
          <p className="mt-1 text-xs opacity-90">
            We could not read what the carrier has on file for this client. Retry the read
            above; the form comes back with it.
          </p>
        </NoticeBox>
      ) : (
        <>
          <OnFile application={application.data} />
          <DecisionForm
            key={stamp(application.data)}
            application={application.data}
            record={record}
            write={write}
          />
          {record.error != null && <ProblemNotice error={record.error} />}
          {record.data && (
            <NoticeBox tone="ok" icon={<CheckCircle2 className="h-5 w-5" />}>
              <p className="text-xs">
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

const TONE_BADGE: Record<"ok" | "warn" | "stop" | "neutral", string> = {
  ok: "bg-brand-strong text-white",
  warn: "bg-amber-100 text-amber-900 dark:bg-amber-900 dark:text-amber-100",
  stop: "bg-rose-100 text-rose-900 dark:bg-rose-900 dark:text-rose-100",
  neutral: "bg-brand-soft text-brand-strong",
};

/** What the carrier has on file right now, read from the server and never echoed. */
function OnFile({ application }: { application: CarrierApplication }) {
  if (!application.recorded) {
    return (
      <NoticeBox
        tone="neutral"
        icon={<FileWarning className="h-5 w-5" />}
        title="Nothing sent to the carrier yet"
      >
        <p className="mt-1 text-xs opacity-90">
          The normal state of a new account, and not something this screen can move: the
          client uploads their own registration documents from their verification screen,
          because only they hold them. There is nothing to record until they have.
        </p>
      </NoticeBox>
    );
  }

  const status = asCarrierStatus(application.status);
  const copy = status ? CARRIER_STATUS_COPY[status] : null;
  const rows: { label: string; value: string | null }[] = [
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
  ].filter((row) => row.value !== null && row.value !== "");

  return (
    <Card
      title="Application on file"
      action={
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={
              "rounded-full px-2 py-0.5 text-xs font-medium " +
              TONE_BADGE[copy?.tone ?? "neutral"]
            }
          >
            {carrierStatusLabel(application.status) ?? "unknown"}
          </span>
          {/* The SERVER's predicate, displayed and never recomputed: the purchase gate
              and this badge must not be capable of disagreeing about whether a state is
              good enough for a number. */}
          <span className="text-xs text-ink-muted">
            {application.is_accepted ? "numbers open" : "numbers closed"}
          </span>
        </div>
      }
    >
      {copy ? (
        <p className="-mt-1 mb-3 text-xs text-ink-muted">{copy.meaning}</p>
      ) : (
        /* FAIL VISIBLE. A state this build has no word for is exactly the one worth
           reading, so it is printed as the server sent it with what to do about it —
           never blanked, and never quietly treated as one of the states we do know. */
        <p className="-mt-1 mb-3 text-xs text-ink-muted">
          This build has no description for that state. It is printed exactly as the API
          sent it; tell engineering, and record a decision below only if one of the four
          clearly matches what the carrier said.
        </p>
      )}
      <dl className="grid gap-2 sm:grid-cols-2">
        {rows.map((row) => (
          <div key={row.label} className="text-xs">
            <dt className="text-ink-muted">{row.label}</dt>
            <dd className="mt-0.5 break-all font-medium text-ink">{row.value}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

const DECISIONS = Object.keys(CARRIER_DECISIONS) as CarrierDecision[];

/**
 * The write.
 *
 * The decision is chosen first and the fields it must name appear with it, because which
 * field is required is a property OF the decision: an acceptance needs the carrier's
 * reference (a number purchase quotes it), a rejection needs their reason (the client is
 * shown it and is the only person who can act on it). Both are pre-empted here and both
 * are refused again by the route and again by a CHECK constraint underneath it.
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
    <Card title="Record the carrier's decision">
      <p className="-mt-2 text-xs text-ink-muted">
        Record what the carrier actually answered — this does not ask them anything. It is
        written to an append-only audit trail with your name on it, and it is what the
        client sees on their own verification screen.
      </p>

      <form
        className="mt-4 space-y-4"
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
          <div className="mt-1">
            <select
              id="carrier-decision"
              value={decision}
              disabled={!write.allowed}
              onChange={(e) => {
                setDecision(e.target.value as CarrierDecision);
                record.reset();
              }}
              className={FIELD}
            >
              {DECISIONS.map((value) => (
                <option key={value} value={value}>
                  {CARRIER_DECISIONS[value].label}
                </option>
              ))}
            </select>
          </div>
          <span id="carrier-decision-hint" className={FIELD_HINT}>
            {spec.effect}
          </span>
        </div>

        {decision === "accepted" && (
          <div>
            <label htmlFor="carrier-reference" className={FIELD_LABEL}>
              Carrier&apos;s application reference
            </label>
            <div className="mt-1">
              <input
                id="carrier-reference"
                type="text"
                maxLength={200}
                value={body.carrier_application_id ?? ""}
                disabled={!write.allowed}
                onChange={(e) => set("carrier_application_id", e.target.value)}
                aria-describedby="carrier-reference-hint"
                className={FIELD}
              />
            </div>
            <span id="carrier-reference-hint" className={FIELD_HINT}>
              Copy it from the carrier&apos;s console exactly as printed. Every number
              purchase for this client quotes it.
            </span>
          </div>
        )}

        {decision === "rejected" && (
          <div>
            <label htmlFor="carrier-reason" className={FIELD_LABEL}>
              Why the carrier refused it
            </label>
            <div className="mt-1">
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
            </div>
            <span id="carrier-reason-hint" className={FIELD_HINT}>
              Shown to the client on their own screen, so write it as something they can
              act on — which document was wrong, and what to send instead.
            </span>
          </div>
        )}

        {blocked && (
          <NoticeBox tone="warn" icon={<AlertTriangle className="h-5 w-5" />}>
            <p className="text-xs">{blocked}</p>
          </NoticeBox>
        )}

        <button
          type="submit"
          className={PRIMARY_BUTTON}
          disabled={!write.allowed || blocked !== null || record.isPending}
        >
          {record.isPending ? "Recording…" : "Record decision"}
        </button>
      </form>
    </Card>
  );
}
