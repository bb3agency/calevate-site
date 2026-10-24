"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Check, Clock3 } from "lucide-react";

import { ActionButton, useActionFeedback, useAsyncAction } from "@/components/arc/feedback";
import { RadioGroup } from "@/components/arc/radio-group";
import { StatusPill } from "@/components/console/statusPill";
import { FileDrop, FileSummary } from "@/components/fileDrop";
import {
  Disclosure,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatIST,
  formatISTDay,
  type NoticeTone,
} from "@/components/ui";
import type { WriteAccess } from "@/lib/api/hooks";
import { ENTITY_TYPES, entityTypeLabel, type KycRecord } from "@/lib/api/kyc";
import type { Session, UploadProgress } from "@/lib/api/client";
import { ViewerBlockedError } from "@/lib/api/protectedFile";
import {
  ACCEPT_ATTRIBUTE,
  BUSINESS_DOCUMENT_KINDS,
  DIGILOCKER_OUTCOME,
  GSTIN_PATTERN,
  OWNER_ID_KIND,
  fileProblem,
  forgetPendingRun,
  openOwnCertificate,
  panProblem,
  readPendingRun,
  rememberPendingRun,
  useAcceptPledge,
  useCompleteDigiLocker,
  useSaveBusinessDetails,
  useStartDigiLocker,
  useSubmitForReview,
  useUploadKycDocument,
  type OutboundPledge,
} from "@/lib/api/verifyBusiness";
import { lookup } from "@/lib/lookup";

/** Who may change what, as the server will rule it. Uploads and the pledge are the
 *  business's own acts: a view-as operator is refused those even holding `org:manage`. */
export type Access = { write: WriteAccess; upload: WriteAccess; pledge: WriteAccess };

export type StepId = "details" | "certificate" | "owner" | "pledge";
type StepState = "done" | "todo" | "waiting" | "locked";
export type StepStatus = { id: StepId; number: number; title: string; state: StepState; word: string };

const STEP_TITLES: Record<StepId, string> = {
  details: "Business details",
  certificate: "Business certificate",
  owner: "The owner's identity",
  pledge: "No-cold-calls pledge and calling disclosure",
};

function inReview(record: KycRecord): boolean {
  return record.status === "submitted" || record.status === "in_review";
}

function detailsSaved(record: KycRecord): boolean {
  return Boolean(record.legal_business_name && record.entity_type && record.gst_registered !== null);
}

function businessDocument(record: KycRecord) {
  return record.documents.find((document) => document.slot === "business");
}

/**
 * Each step's state in a word, from the records the server returned. The KYC verdict comes
 * from `is_verified`, never from `status`: the gate asks the first, and a step painted done
 * off the second would disagree with it on the day a verification lapses.
 *
 * `pledge` undefined means its read failed; that step is then "not loaded", never "to do".
 */
export function stepStatuses(record: KycRecord, pledge: OutboundPledge | undefined): StepStatus[] {
  const verified = record.is_verified;
  const reviewing = inReview(record);
  const saved = detailsSaved(record);
  const certificate = businessDocument(record);
  const step = (id: StepId, number: number, state: StepState, word: string): StepStatus => ({
    id,
    number,
    title: STEP_TITLES[id],
    state,
    word,
  });
  return [
    verified || reviewing
      ? step("details", 1, "done", verified ? "Done" : "Sent")
      : saved
        ? step("details", 1, "done", "Saved")
        : step("details", 1, "todo", "To do"),
    verified
      ? step("certificate", 2, "done", "Done")
      : certificate
        ? step("certificate", 2, "done", reviewing ? "Sent" : "Uploaded")
        : saved
          ? step("certificate", 2, "todo", "To do")
          : step("certificate", 2, "locked", "After step 1"),
    record.digilocker_outstanding
      ? step("owner", 3, "todo", "DigiLocker check needed")
      : verified
        ? step("owner", 3, "done", "Verified")
        : reviewing
          ? step("owner", 3, "waiting", "In review")
          : saved && certificate
            ? step("owner", 3, "todo", record.status === "rejected" ? "Send again" : "To do")
            : step("owner", 3, "locked", "After steps 1 and 2"),
    pledge === undefined
      ? step("pledge", 4, "locked", "Not loaded")
      : pledge.is_current
        ? step("pledge", 4, "done", "Accepted")
        : step("pledge", 4, "todo", pledge.accepted_version === null ? "To do" : "Accept the new version"),
  ];
}

/**
 * The four steps that open outgoing calls, as one numbered list: each with its state in a
 * word, one line saying what we need, and the form that does it. The first step left to do
 * is drawn as the next one; finished steps keep their content (a saved certificate stays
 * viewable) but say less.
 */
export function VerificationSteps({
  session,
  record,
  pledge,
  pledgeError,
  onPledgeRetry,
  access,
}: {
  session: Session;
  record: KycRecord;
  pledge: OutboundPledge | undefined;
  pledgeError: unknown;
  onPledgeRetry: () => void;
  access: Access;
}) {
  const statuses = stepStatuses(record, pledge);
  const nextId = statuses.find((status) => status.state === "todo")?.id;
  const done = statuses.filter((status) => status.state === "done").length;
  const locked = record.is_verified || inReview(record);
  const byId = Object.fromEntries(statuses.map((status) => [status.id, status])) as Record<StepId, StepStatus>;

  return (
    <section aria-labelledby="verify-steps" className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="verify-steps" className="text-heading text-ink">
          Steps to open outgoing calls
        </h2>
        <span className="text-meta tabular-nums text-ink-muted">
          {done === statuses.length ? "All done" : `${done} of ${statuses.length} done`}
        </span>
      </div>
      {!locked && <RestrictionNote reason={access.write.reason ?? access.upload.reason} />}
      <ol className="space-y-0">
        <Step
          status={byId.details}
          next={nextId === "details"}
          needed="The legal name, how the business is registered, and the GSTIN if it is registered for GST."
        >
          {locked ? (
            <SavedDetails record={record} />
          ) : detailsSaved(record) ? (
            // Saved and still changeable until the review starts: the answer first, the form
            // one tap away, so a finished step does not cost a phone a screen of fields.
            <div className="space-y-2">
              <SavedDetails record={record} />
              <Disclosure variant="inline" headingLevel={4} title="Change the details" showLabel="Open" hideLabel="Close">
                <div className="pt-2">
                  <DetailsForm session={session} record={record} access={access.write} />
                </div>
              </Disclosure>
            </div>
          ) : (
            <DetailsForm session={session} record={record} access={access.write} />
          )}
        </Step>
        <Step
          status={byId.certificate}
          next={nextId === "certificate"}
          needed="One certificate: the GST certificate, or the Certificate of Incorporation or Udyam certificate."
        >
          <BusinessDocument session={session} record={record} access={access.upload} />
        </Step>
        <Step
          status={byId.owner}
          next={nextId === "owner"}
          needed="The owner's PAN card for our review, or a DigiLocker check with Aadhaar or PAN."
        >
          <OwnerStep session={session} record={record} access={access} />
        </Step>
        <Step
          status={byId.pledge}
          next={nextId === "pledge"}
          needed="Somebody at the business reads it and accepts it on the business's behalf."
          last
        >
          {pledge ? (
            <PledgeBody session={session} pledge={pledge} access={access.pledge} />
          ) : (
            <ProblemNotice error={pledgeError ?? new Error("The pledge did not load.")} onRetry={onPledgeRetry} />
          )}
        </Step>
      </ol>
    </section>
  );
}

const PILL_TONE: Record<StepState, NoticeTone> = {
  done: "ok",
  todo: "warn",
  waiting: "neutral",
  locked: "neutral",
};

/** One step: a marker on a rail, the title with its state, what we need, and the form. */
function Step({
  status,
  next,
  needed,
  last = false,
  children,
}: {
  status: StepStatus;
  next: boolean;
  needed: string;
  last?: boolean;
  children: ReactNode;
}) {
  const headingId = useId();
  const quiet = status.state === "done" || status.state === "locked";
  return (
    <li id={`step-${status.id}`} aria-labelledby={headingId} className="relative flex scroll-mt-24 gap-3 sm:gap-4">
      <div className="flex flex-col items-center">
        <Marker status={status} next={next} />
        {!last && <span aria-hidden className="mt-1 w-px flex-1 bg-line" />}
      </div>
      <div className={`min-w-0 flex-1 ${last ? "" : "pb-8"}`}>
        <div className="flex min-h-7 flex-wrap items-center gap-x-3 gap-y-1">
          <h3 id={headingId} className={`text-[15px] font-semibold ${quiet ? "text-ink-muted" : "text-ink"}`}>
            <span className="sr-only">Step {status.number}: </span>
            {status.title}
          </h3>
          <StatusPill tone={next ? "warn" : PILL_TONE[status.state]}>{next ? "Next" : status.word}</StatusPill>
        </div>
        {status.state !== "done" && <p className="mt-0.5 max-w-prose text-sm text-ink-muted">{needed}</p>}
        <div className="mt-3">{children}</div>
      </div>
    </li>
  );
}

function Marker({ status, next }: { status: StepStatus; next: boolean }) {
  const base = "flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-meta font-semibold tabular-nums";
  if (status.state === "done") {
    return (
      <span aria-hidden className={`${base} bg-brand-strong text-white`}>
        <Check className="h-3.5 w-3.5" strokeWidth={3} />
      </span>
    );
  }
  if (status.state === "waiting") {
    return (
      <span aria-hidden className={`${base} bg-ink/[0.06] text-ink-muted`}>
        <Clock3 className="h-3.5 w-3.5" />
      </span>
    );
  }
  return (
    <span
      aria-hidden
      className={`${base} ${next ? "bg-brand-soft text-brand-strong ring-2 ring-brand" : "border-[1.5px] border-ink/25 text-ink-muted"}`}
    >
      {status.number}
    </span>
  );
}

/** The details as saved, once they can no longer be changed (with us, or verified). */
function SavedDetails({ record }: { record: KycRecord }) {
  const rows = [
    { label: "Legal name", value: record.legal_business_name },
    { label: "Registered as", value: entityTypeLabel(record.entity_type) },
    { label: "GSTIN", value: record.gst_registered ? record.gstin : record.gst_registered === false ? "Not registered for GST" : null },
  ].filter((row) => row.value);
  if (rows.length === 0) return <p className="text-sm text-ink">Checked by our team.</p>;
  return (
    <dl className="space-y-1 text-sm">
      {rows.map((row) => (
        <div key={row.label} className="flex flex-wrap gap-x-2">
          <dt className="text-ink-muted">{row.label}:</dt>
          <dd className="min-w-0 font-medium text-ink [overflow-wrap:anywhere]">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function DetailsForm({ session, record, access }: { session: Session; record: KycRecord; access: WriteAccess }) {
  const save = useSaveBusinessDetails(session);
  const saveFeedback = useActionFeedback(save, { errorDisplay: "inline" });
  const [entityType, setEntityType] = useState(record.entity_type ?? "");
  const [name, setName] = useState(record.legal_business_name ?? "");
  const [gst, setGst] = useState<boolean | null>(record.gst_registered ?? null);
  const [gstin, setGstin] = useState(record.gstin ?? "");
  const [gstinTouched, setGstinTouched] = useState(false);
  const [owner, setOwner] = useState(record.signatory_name ?? "");
  const gstinBad = gst === true && !GSTIN_PATTERN.test(gstin.trim().toUpperCase());
  const ready = entityType && name.trim().length >= 2 && gst !== null && owner.trim().length >= 2 && !gstinBad;
  const gstinErrorId = useId();
  // Said once the field is left (or on a save attempt), not on every keystroke of a
  // 15-character code the person is still typing.
  const showGstinError = gstinBad && gstin !== "" && gstinTouched;

  return (
    <form
      noValidate
      className="max-w-md space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        setGstinTouched(true);
        if (!ready || gst === null) return;
        saveFeedback.run({
          entity_type: entityType,
          legal_business_name: name.trim(),
          gst_registered: gst,
          gstin: gst ? gstin.trim().toUpperCase() : null,
          owner_name: owner.trim(),
        });
      }}
    >
      <label className="block">
        <span className={FIELD_LABEL}>Legal name, as on the certificate</span>
        <input
          className={FIELD}
          value={name}
          onChange={(event) => setName(event.target.value)}
          maxLength={200}
          autoComplete="organization"
        />
      </label>
      <label className="block">
        <span className={FIELD_LABEL}>How the business is registered</span>
        <select className={FIELD} value={entityType} onChange={(event) => setEntityType(event.target.value)}>
          <option value="">Choose…</option>
          {Object.entries(ENTITY_TYPES).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <RadioGroup
        label="Registered for GST?"
        name="gst"
        inline
        options={[
          { value: "yes", label: "Yes" },
          { value: "no", label: "No" },
        ]}
        value={gst === null ? null : gst ? "yes" : "no"}
        onChange={(value) => setGst(value === "yes")}
      />
      {gst && (
        <label className="block">
          <span className={FIELD_LABEL}>GSTIN</span>
          <input
            className={`${FIELD} font-mono uppercase`}
            value={gstin}
            onChange={(event) => setGstin(event.target.value)}
            onBlur={() => setGstinTouched(true)}
            maxLength={15}
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            aria-invalid={showGstinError}
            aria-describedby={showGstinError ? gstinErrorId : undefined}
          />
          {showGstinError && (
            <span id={gstinErrorId} className="mt-1 block text-sm text-danger">
              A GSTIN is 15 characters, like 36AABCT1234C1Z5.
            </span>
          )}
        </label>
      )}
      <label className="block">
        <span className={FIELD_LABEL}>Owner or authorised signatory, as on their ID</span>
        <input
          className={FIELD}
          value={owner}
          onChange={(event) => setOwner(event.target.value)}
          maxLength={120}
          autoComplete="name"
        />
      </label>
      <div>
        <ActionButton
          type="submit"
          status={saveFeedback.status}
          disabled={!access.allowed || !ready}
          title={access.reason ?? undefined}
          pendingLabel="Saving…"
          successLabel="Saved"
        >
          Save details
        </ActionButton>
        <ProblemNotice error={save.error} />
      </div>
    </form>
  );
}

/** What a KYC upload takes, as `fileProblem` and the server check it. */
const KYC_FILE_HINT = "PDF, JPEG or PNG, up to 5 MB.";

/**
 * A KYC file control: the kit's `FileDrop` with this page's rules (`fileProblem`, the
 * preview of the server's), sending on pick with real progress.
 */
function KycFileDrop({
  label,
  disabled,
  onPick,
}: {
  label: string;
  disabled: boolean;
  onPick: (file: File, onProgress: (progress: UploadProgress) => void) => Promise<unknown>;
}) {
  const [sending, setSending] = useState<{ file: File; percent: number | null } | null>(null);
  return (
    <FileDrop
      label={label}
      hint={KYC_FILE_HINT}
      accept={ACCEPT_ATTRIBUTE}
      validate={fileProblem}
      disabled={disabled || sending !== null}
      sending={sending}
      onFiles={([file]) => {
        setSending({ file, percent: 0 });
        // Cleared on both outcomes: a bar left at 100% under a refusal says the file arrived.
        void onPick(file, ({ loaded, total }) =>
          setSending({ file, percent: total ? Math.min(100, Math.round((loaded / total) * 100)) : null }),
        )
          .catch(() => undefined)
          .finally(() => setSending(null));
      }}
    />
  );
}

/** The review state, in the client's words, for the certificate on file. */
function certificateStatus(record: KycRecord): string {
  if (record.is_verified) return "Verified";
  if (inReview(record)) return "With our review team";
  if (record.status === "rejected") return "Not accepted — see our note at the top";
  return "Not sent for review yet";
}

function BusinessDocument({ session, record, access }: { session: Session; record: KycRecord; access: WriteAccess }) {
  const upload = useUploadKycDocument(session);
  // The drop zone shows the upload's progress, and the notice under it any refusal.
  useActionFeedback(upload, { errorDisplay: "inline" });
  const current = businessDocument(record);
  const options = record.gst_registered ? (["gst"] as const) : (["incorporation", "udyam"] as const);
  const [kind, setKind] = useState<string>(options[0]);
  const view = useAsyncAction((id: string) => openOwnCertificate(session, id), { errorDisplay: "inline" });
  const openError = view.status === "error" ? view.error : null;
  // The server's own lock: replaceable until the review starts, and never once verified.
  const reviewing = inReview(record);
  const replaceable = !record.is_verified && !reviewing;

  if (!current && record.is_verified) return <p className="text-sm text-ink">Checked by our team.</p>;

  return (
    <div className="space-y-3">
      {current ? (
        <FileSummary
          name={current.filename}
          type={current.content_type}
          size={current.size_bytes}
          meta={
            <>
              {lookup(BUSINESS_DOCUMENT_KINDS, current.kind) ?? "Certificate"} · uploaded {formatIST(current.uploaded_at)}
              <span className="mt-1 block font-medium text-ink">{certificateStatus(record)}</span>
            </>
          }
          action={
            current.held && (
              <ActionButton
                variant="secondary-sm"
                status={view.status}
                onClick={() => view.run(current.id)}
                pendingLabel="Opening…"
                successLabel="Opened"
              >
                View
              </ActionButton>
            )
          }
        />
      ) : record.gst_registered === null ? (
        <p className="text-sm text-ink-muted">Save the business details first, so we know which certificate to ask for.</p>
      ) : (
        <p className="text-sm text-ink">
          {record.gst_registered
            ? "Upload the GST registration certificate."
            : "Upload the Certificate of Incorporation, or the Udyam registration certificate."}
        </p>
      )}
      {openError instanceof ViewerBlockedError ? (
        <p role="alert" className="text-sm text-danger">
          {openError.message}
        </p>
      ) : (
        openError != null && <ProblemNotice error={openError} />
      )}
      {record.is_verified && current && (
        <p className={FIELD_HINT}>Your business is verified, so the certificate can no longer be changed.</p>
      )}
      {reviewing && current && (
        <p className={FIELD_HINT}>It is with our review team, so it cannot be changed until the review is done.</p>
      )}
      {replaceable && record.gst_registered !== null && (
        <div className="max-w-md space-y-3">
          {!record.gst_registered && (
            <label className="block">
              <span className={FIELD_LABEL}>Which certificate</span>
              <select className={FIELD} value={kind} onChange={(event) => setKind(event.target.value)}>
                {options.map((value) => (
                  <option key={value} value={value}>
                    {BUSINESS_DOCUMENT_KINDS[value]}
                  </option>
                ))}
              </select>
            </label>
          )}
          <KycFileDrop
            disabled={!access.allowed || upload.isPending}
            label={current ? "Replace the certificate" : "Choose the certificate"}
            onPick={(file, onProgress) =>
              upload.mutateAsync({ slot: "business", kind: record.gst_registered ? "gst" : kind, file, onProgress })
            }
          />
          <ProblemNotice error={upload.error} />
        </div>
      )}
    </div>
  );
}

function OwnerStep({ session, record, access }: { session: Session; record: KycRecord; access: Access }) {
  const locked = record.is_verified || inReview(record);
  const ready = detailsSaved(record) && Boolean(businessDocument(record));
  const [path, setPath] = useState<"manual" | "digilocker">(record.kyc_path === "digilocker" ? "digilocker" : "manual");

  if (locked && !record.digilocker_outstanding) {
    return (
      <div className="space-y-1">
        <p className="text-sm text-ink">
          {record.is_verified
            ? "Your business is verified."
            : "Your documents are with our review team. We will let you know when the review is done."}
        </p>
        {record.owner_id_masked && (
          <p className={FIELD_HINT}>
            Owner ID on record: {record.owner_id_type === "pan" ? "PAN" : "Aadhaar"} {record.owner_id_masked}
          </p>
        )}
      </div>
    );
  }
  if (!record.digilocker_outstanding && !ready) {
    return <p className="text-sm text-ink-muted">Opens once the business details are saved and the certificate is uploaded.</p>;
  }
  return (
    <div className="max-w-md space-y-4">
      {record.digilocker_outstanding && record.digilocker_required_reason && (
        <p className="text-sm text-ink">
          <span className="font-semibold">Why we asked:</span> {record.digilocker_required_reason}
        </p>
      )}
      {!record.digilocker_outstanding && (
        <RadioGroup
          label="How would you like to verify?"
          name="kyc-path"
          options={[
            { value: "manual", label: "Upload the owner's PAN card for our review" },
            { value: "digilocker", label: "Verify with DigiLocker" },
          ]}
          value={path}
          onChange={(value) => setPath(value === "digilocker" ? "digilocker" : "manual")}
        />
      )}
      {locked && <RestrictionNote reason={access.write.reason} />}
      {path === "manual" && !record.digilocker_outstanding ? (
        <ManualPath session={session} record={record} access={access} />
      ) : (
        <DigiLockerPath session={session} record={record} access={access.write} />
      )}
    </div>
  );
}

function ManualPath({ session, record, access }: { session: Session; record: KycRecord; access: Access }) {
  const upload = useUploadKycDocument(session);
  useActionFeedback(upload, { errorDisplay: "inline" });
  const submit = useSubmitForReview(session);
  const submitFeedback = useActionFeedback(submit, { errorDisplay: "inline" });
  const owner = record.documents.find((document) => document.slot === "owner_id" && document.held);
  const [number, setNumber] = useState("");
  const [numberTouched, setNumberTouched] = useState(false);
  const numberProblem = number ? panProblem(number) : null;
  const panErrorId = useId();
  const panHintId = useId();
  const showProblem = numberProblem !== null && numberTouched;

  return (
    <div className="space-y-4">
      <p className="text-sm text-ink">
        Upload a clear photo or scan of the owner&apos;s PAN card. We check the PAN, the name and the date of birth
        with the Income Tax Department. We cannot accept an Aadhaar card here.
        {record.self_verification_available && " To use your Aadhaar, verify with DigiLocker instead."}
      </p>
      {owner && <FileSummary name={owner.filename} type={owner.content_type} size={owner.size_bytes} />}
      <KycFileDrop
        disabled={!access.upload.allowed || upload.isPending}
        label={owner ? "Replace the PAN card" : "Choose the PAN card"}
        onPick={(file, onProgress) => upload.mutateAsync({ slot: "owner_id", kind: OWNER_ID_KIND, file, onProgress })}
      />
      <ProblemNotice error={upload.error} />
      <label className="block">
        <span className={FIELD_LABEL}>PAN</span>
        <input
          className={`${FIELD} font-mono uppercase`}
          value={number}
          onChange={(event) => setNumber(event.target.value)}
          onBlur={() => setNumberTouched(true)}
          maxLength={10}
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          aria-invalid={showProblem}
          aria-describedby={showProblem ? `${panHintId} ${panErrorId}` : panHintId}
        />
        <span id={panHintId} className={FIELD_HINT}>
          We keep only a masked form, like XXXXX1234X. The PAN card file is deleted as soon as our review is done,
          and after 30 days if it is not reviewed.
        </span>
        {showProblem && (
          <span id={panErrorId} className="mt-1 block text-sm text-danger">
            {numberProblem}
          </span>
        )}
      </label>
      <ActionButton
        status={submitFeedback.status}
        disabled={!access.write.allowed || !owner || !number || Boolean(numberProblem)}
        onClick={() => submitFeedback.run({ owner_id_type: "pan", owner_id_number: number.trim().toUpperCase() })}
        pendingLabel="Sending…"
        successLabel="Sent"
      >
        Send for review
      </ActionButton>
      <ProblemNotice error={submit.error} />
    </div>
  );
}

function DigiLockerPath({ session, record, access }: { session: Session; record: KycRecord; access: WriteAccess }) {
  const start = useStartDigiLocker(session);
  const startFeedback = useActionFeedback(start, { errorDisplay: "inline" });
  const [document, setDocument] = useState<"aadhaar" | "pan">("aadhaar");
  if (!record.self_verification_available) {
    // We asked for DigiLocker on this account, and only a DigiLocker run clears that
    // request (`kyc.KycState.digilocker_outstanding`): an uploaded ID cannot, so pointing
    // the client at the upload would send them round in a circle.
    return record.digilocker_outstanding ? (
      <p className="text-sm text-ink">
        DigiLocker verification is temporarily unavailable, and uploading the owner&apos;s PAN card
        cannot replace the DigiLocker check we asked for. Please contact us and we will sort it
        out with you.
      </p>
    ) : (
      <p className="text-sm text-ink">
        DigiLocker verification is not available yet. Please upload the owner&apos;s PAN card for our review instead.
      </p>
    );
  }
  return (
    <div className="space-y-3">
      <p className="text-sm text-ink">
        You sign in to DigiLocker on its own page and share one record. We receive only whether it succeeded, the
        name on it and a masked number, never the document.
      </p>
      <RadioGroup
        label="Which record to share"
        name="id-doc"
        inline
        options={[
          { value: "aadhaar", label: "Aadhaar" },
          { value: "pan", label: "PAN" },
        ]}
        value={document}
        onChange={(value) => setDocument(value === "pan" ? "pan" : "aadhaar")}
      />
      <ActionButton
        // Success hands the page to DigiLocker, so the tick reads as the redirect starting.
        status={startFeedback.status}
        disabled={!access.allowed || !record.entity_type}
        title={access.reason ?? undefined}
        pendingLabel="Opening DigiLocker…"
        successLabel="Opening DigiLocker…"
        onClick={() =>
          start.mutate(
            { entity_type: record.entity_type ?? "", id_document: document },
            {
              onSuccess: (run) => {
                rememberPendingRun(session.orgSlug, run.provider_ref);
                window.location.assign(run.redirect_url);
              },
            },
          )
        }
      >
        Continue to DigiLocker
      </ActionButton>
      <ProblemNotice error={start.error} />
    </div>
  );
}

function PledgeBody({ session, pledge, access }: { session: Session; pledge: OutboundPledge; access: WriteAccess }) {
  const accept = useAcceptPledge(session);
  const acceptFeedback = useActionFeedback(accept, { errorDisplay: "inline" });
  const [read, setRead] = useState(false);
  const acceptedOn = formatISTDay(pledge.accepted_at);
  return (
    <div className="space-y-3">
      {/* The server separates the pledge and the disclosure with a blank line (D-762). A rule
          on the left, not a grey box: a box inside the step adds no level to the hierarchy. */}
      <blockquote className="max-w-prose whitespace-pre-line border-l-2 border-line pl-4 text-sm text-ink">
        {pledge.pledge_text}
      </blockquote>
      {pledge.is_current ? (
        <p className="text-sm text-ink">{acceptedOn ? `Accepted on ${acceptedOn}.` : "Accepted."}</p>
      ) : (
        <div className="space-y-3">
          {pledge.accepted_version !== null && (
            <p className="text-sm text-ink">
              The pledge changed since you accepted version {pledge.accepted_version}. Please read and accept it again.
            </p>
          )}
          <RestrictionNote reason={access.reason} />
          <label className="flex items-start gap-3 text-sm text-ink touch:min-h-11">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 shrink-0 accent-brand-strong touch:h-5 touch:w-5"
              checked={read}
              disabled={!access.allowed}
              onChange={(event) => setRead(event.target.checked)}
            />
            I have read the pledge and the disclosure, and accept them on behalf of the business.
          </label>
          <ActionButton
            status={acceptFeedback.status}
            disabled={!access.allowed || !read}
            onClick={() => acceptFeedback.run(pledge)}
            pendingLabel="Accepting…"
            successLabel="Accepted"
          >
            Accept the pledge
          </ActionButton>
          <ProblemNotice error={accept.error} />
        </div>
      )}
    </div>
  );
}

/** Finishes a run when the client comes back from DigiLocker, and says how it ended. */
export function DigiLockerReturn({ session }: { session: Session }) {
  const complete = useCompleteDigiLocker(session);
  // Every outcome, a refusal included, renders as this component's own notice.
  const completeFeedback = useActionFeedback(complete, { errorDisplay: "inline" });
  const asked = useRef(false);
  const [ref, setRef] = useState<string | null>(null);

  const org = session.orgSlug;

  useEffect(() => {
    if (asked.current) return;
    asked.current = true;
    const fromUrl = new URLSearchParams(window.location.search).get("provider_ref");
    const run = readPendingRun(org) ?? fromUrl;
    if (!run) return;
    setRef(run);
    complete.mutate(run, {
      onSuccess: (result) => {
        // `pending` is the only outcome worth asking about again.
        if (result.status !== "pending") finished(org);
      },
      // A refusal is final for this reference too (another account's run, an unknown one,
      // verification switched off), so it must not greet every later visit to the page.
      onError: () => forgetPendingRun(org),
    });
  }, [complete, org]);

  if (!ref) return null;
  if (complete.isPending) return <Skeleton rows={2} />;
  if (complete.error) return <ProblemNotice error={complete.error} />;
  if (complete.data?.status === "pending") {
    return (
      <NoticeBox
        tone="warn"
        title="DigiLocker has not finished yet"
        action={
          <ActionButton
            variant="secondary"
            status={completeFeedback.status}
            onClick={() => completeFeedback.run(ref)}
            successLabel="Checked"
          >
            Check again
          </ActionButton>
        }
      >
        If you completed it, wait a moment and check again.
      </NoticeBox>
    );
  }
  const outcome = complete.data ? lookup(DIGILOCKER_OUTCOME, complete.data.status) : undefined;
  if (outcome) {
    return (
      <NoticeBox tone={outcome.tone} title={outcome.title}>
        {outcome.body}
      </NoticeBox>
    );
  }
  return null;
}

/** The run has an outcome: forget it, and drop the reference from the address so a reload
 *  does not ask about it again. */
function finished(org: string): void {
  forgetPendingRun(org);
  try {
    const url = new URL(window.location.href);
    if (!url.searchParams.has("provider_ref")) return;
    url.searchParams.delete("provider_ref");
    window.history.replaceState(window.history.state, "", url.toString());
  } catch {
    // The address keeps the reference; a reload answers "already recorded".
  }
}
