"use client";

import { useEffect, useRef, useState } from "react";
import { CheckCircle2, ShieldAlert } from "lucide-react";

import { FileDrop, FileSummary } from "@/components/fileDrop";

import { PageHeader } from "@/components/console/pageHeader";
import {
  Card,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { useActAccess, useWriteAccess, type WriteAccess } from "@/lib/api/hooks";
import { ENTITY_TYPES, useKycRecord, type KycRecord } from "@/lib/api/kyc";
import { useClientSession } from "@/lib/api/session";
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
  outboundSteps,
  panProblem,
  readPendingRun,
  rememberPendingRun,
  useAcceptPledge,
  useCompleteDigiLocker,
  useOutboundPledge,
  useSaveBusinessDetails,
  useStartDigiLocker,
  useSubmitForReview,
  useUploadKycDocument,
  type OutboundPledge,
} from "@/lib/api/verifyBusiness";
import { lookup } from "@/lib/lookup";

import { PhoneNumbersNext } from "./PhoneNumbersNext";
import { TrialLockNotice } from "../TrialLockNotice";

/** Who may change what on this page, as the server will rule it. Uploads and the pledge are
 *  the business's own acts: a view-as operator is refused those even holding `org:manage`. */
type Access = { write: WriteAccess; upload: WriteAccess };

/**
 * Verify your business (D-692) — the page that opens outbound calling.
 *
 * Outbound needs a verified business and an accepted no-cold-calls pledge, on every plan.
 * Inbound calls never depend on either, and the page says so first. The client chooses
 * the path: upload the owner's ID for our review, or verify through DigiLocker. The
 * business certificate and details are needed on both, so they come first.
 *
 * Client-facing text names no telecom or voice vendor, and no identity provider either.
 */
export default function VerifyBusinessPage() {
  const session = useClientSession();
  const kyc = useKycRecord(session);
  const pledge = useOutboundPledge(session);
  const access: Access = {
    write: useWriteAccess(session, "org:manage", "verify the business"),
    upload: useActAccess(session, "org:manage", "compliance.kyc_documents", "upload verification documents"),
  };
  const pledgeAccess = useActAccess(session, "org:manage", "compliance.outbound_pledge", "accept the pledge");

  if (kyc.isLoading || pledge.isLoading) return <Skeleton rows={8} />;
  const record = kyc.data;

  return (
    <div className="space-y-6 pb-12">
      <PageHeader
        description={
          <>
            Before this account can place outgoing calls, we verify the business and you
            promise not to cold-call. Calls coming in are never affected.
          </>
        }
      />
      {kyc.error && <ProblemNotice error={kyc.error} onRetry={() => void kyc.refetch()} />}
      {pledge.error && <ProblemNotice error={pledge.error} onRetry={() => void pledge.refetch()} />}
      {record && <OutboundStatus record={record} pledge={pledge.data} />}
      {pledge.data && <PledgeCard session={session} pledge={pledge.data} access={pledgeAccess} />}
      <TrialLockNotice lock="kyc" />
      {record && <VerifyCards session={session} record={record} access={access} />}
      <PhoneNumbersNext />
    </div>
  );
}

function OutboundStatus({ record, pledge }: { record: KycRecord; pledge: OutboundPledge | undefined }) {
  const steps = outboundSteps(record, pledge);
  if (steps.length === 0) {
    return (
      <NoticeBox tone="ok" icon={<CheckCircle2 aria-hidden className="h-5 w-5" />} title="Outgoing calls are open">
        <p className="mt-1">Your business is verified and the pledge is accepted.</p>
      </NoticeBox>
    );
  }
  return (
    <NoticeBox tone="warn" icon={<ShieldAlert aria-hidden className="h-5 w-5" />} title="Outgoing calls are paused">
      <ul className="mt-1 list-disc pl-5">
        {steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ul>
      <p className="mt-2 font-semibold">Calls coming in are unaffected — your agent keeps answering.</p>
      {record.digilocker_outstanding && record.digilocker_required_reason && (
        <p className="mt-2">Why we asked: {record.digilocker_required_reason}</p>
      )}
    </NoticeBox>
  );
}

function PledgeCard({
  session,
  pledge,
  access,
}: {
  session: Session;
  pledge: OutboundPledge;
  access: WriteAccess;
}) {
  const accept = useAcceptPledge(session);
  const [read, setRead] = useState(false);
  return (
    <Card title="No-cold-calls pledge">
      <blockquote className="rounded-md bg-surface-muted p-4 text-sm text-ink">{pledge.pledge_text}</blockquote>
      <p className={FIELD_HINT}>Version {pledge.version}.</p>
      {pledge.is_current ? (
        <p className="mt-3 text-sm text-ink">
          Accepted
          {pledge.accepted_at ? ` on ${new Date(pledge.accepted_at).toLocaleDateString("en-IN")}` : ""}.
        </p>
      ) : (
        <div className="mt-3 space-y-3">
          {pledge.accepted_version !== null && (
            <p className="text-sm text-ink">
              The pledge changed since you accepted version {pledge.accepted_version}. Please read and accept it again.
            </p>
          )}
          <RestrictionNote reason={access.reason} />
          <label className="flex items-start gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={read}
              disabled={!access.allowed}
              onChange={(event) => setRead(event.target.checked)}
            />
            I have read this and accept it on behalf of the business.
          </label>
          <button
            type="button"
            className={PRIMARY_BUTTON}
            disabled={!access.allowed || !read || accept.isPending}
            onClick={() => accept.mutate(pledge)}
          >
            Accept the pledge
          </button>
          <ProblemNotice error={accept.error} />
        </div>
      )}
    </Card>
  );
}

function VerifyCards({ session, record, access }: { session: Session; record: KycRecord; access: Access }) {
  const locked = record.is_verified || record.status === "submitted" || record.status === "in_review";
  const business = record.documents.find((document) => document.slot === "business");
  const [path, setPath] = useState<"manual" | "digilocker">(record.kyc_path === "digilocker" ? "digilocker" : "manual");
  const detailsDone = Boolean(record.legal_business_name && record.entity_type && record.gst_registered !== null);

  return (
    <>
      <DigiLockerReturn session={session} />
      {record.status === "rejected" && record.rejection_reason && (
        <NoticeBox tone="stop" title="We could not verify the business from what was sent">
          <p className="mt-1">{record.rejection_reason}</p>
        </NoticeBox>
      )}
      {!locked && <RestrictionNote reason={access.write.reason ?? access.upload.reason} />}
      {!locked && <DetailsCard session={session} record={record} access={access.write} />}
      {(!locked || business) && <BusinessDocumentCard session={session} record={record} access={access.upload} />}
      {locked && !record.digilocker_outstanding && (
        <Card title="Your verification">
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
        </Card>
      )}
      {(!locked || record.digilocker_outstanding) && detailsDone && business && (
        <Card title="Verify the owner">
          {!record.digilocker_outstanding && (
            <fieldset className="mb-4 flex flex-wrap gap-4 text-sm text-ink">
              <legend className={FIELD_LABEL}>How would you like to verify?</legend>
              <label className="flex items-center gap-2">
                <input type="radio" name="kyc-path" checked={path === "manual"} onChange={() => setPath("manual")} />
                Upload the owner&apos;s PAN card for our review
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="radio"
                  name="kyc-path"
                  checked={path === "digilocker"}
                  onChange={() => setPath("digilocker")}
                />
                Verify with DigiLocker
              </label>
            </fieldset>
          )}
          {locked && <RestrictionNote reason={access.write.reason} />}
          {path === "manual" && !record.digilocker_outstanding ? (
            <ManualPath session={session} record={record} access={access} />
          ) : (
            <DigiLockerPath session={session} record={record} access={access.write} />
          )}
        </Card>
      )}
    </>
  );
}

function DetailsCard({ session, record, access }: { session: Session; record: KycRecord; access: WriteAccess }) {
  const save = useSaveBusinessDetails(session);
  const [entityType, setEntityType] = useState(record.entity_type ?? "");
  const [name, setName] = useState(record.legal_business_name ?? "");
  const [gst, setGst] = useState<boolean | null>(record.gst_registered ?? null);
  const [gstin, setGstin] = useState(record.gstin ?? "");
  const [owner, setOwner] = useState(record.signatory_name ?? "");
  const gstinBad = gst === true && !GSTIN_PATTERN.test(gstin.trim().toUpperCase());
  const ready = entityType && name.trim().length >= 2 && gst !== null && owner.trim().length >= 2 && !gstinBad;

  return (
    <Card title="1. Business details">
      <form
        noValidate
        className="grid gap-4 sm:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (!ready || gst === null) return;
          save.mutate({
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
          <input className={FIELD} value={name} onChange={(event) => setName(event.target.value)} maxLength={200} />
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
        <fieldset className="block text-sm text-ink">
          <legend className={FIELD_LABEL}>Registered for GST?</legend>
          <label className="mr-4 inline-flex items-center gap-2">
            <input type="radio" name="gst" checked={gst === true} onChange={() => setGst(true)} /> Yes
          </label>
          <label className="inline-flex items-center gap-2">
            <input type="radio" name="gst" checked={gst === false} onChange={() => setGst(false)} /> No
          </label>
        </fieldset>
        {gst && (
          <label className="block">
            <span className={FIELD_LABEL}>GSTIN</span>
            <input
              className={FIELD}
              value={gstin}
              onChange={(event) => setGstin(event.target.value)}
              maxLength={15}
              aria-invalid={gstinBad}
            />
            {gstinBad && gstin && <span className={FIELD_HINT}>A GSTIN is 15 characters, like 36AABCT1234C1Z5.</span>}
          </label>
        )}
        <label className="block">
          <span className={FIELD_LABEL}>Owner or authorised signatory, as on their ID</span>
          <input className={FIELD} value={owner} onChange={(event) => setOwner(event.target.value)} maxLength={120} />
        </label>
        <div className="sm:col-span-2">
          <button
            type="submit"
            className={PRIMARY_BUTTON}
            disabled={!access.allowed || !ready || save.isPending}
            title={access.reason ?? undefined}
          >
            Save details
          </button>
          {save.isSuccess && <span className="ml-3 text-sm text-ink">Saved.</span>}
          <ProblemNotice error={save.error} />
        </div>
      </form>
    </Card>
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
  if (record.status === "submitted" || record.status === "in_review") return "With our review team";
  if (record.status === "rejected") return "Not accepted — see the note above";
  return "Not sent for review yet";
}

function BusinessDocumentCard({
  session,
  record,
  access,
}: {
  session: Session;
  record: KycRecord;
  access: WriteAccess;
}) {
  const upload = useUploadKycDocument(session);
  const current = record.documents.find((document) => document.slot === "business");
  const options = record.gst_registered
    ? (["gst"] as const)
    : (["incorporation", "udyam"] as const);
  const [kind, setKind] = useState<string>(options[0]);
  const [opening, setOpening] = useState(false);
  const [openError, setOpenError] = useState<unknown>(null);
  // The server's own lock: replaceable until the review starts, and never once verified.
  const inReview = record.status === "submitted" || record.status === "in_review";
  const replaceable = !record.is_verified && !inReview;

  return (
    <Card title="2. Business certificate">
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
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                disabled={opening}
                onClick={() => {
                  setOpenError(null);
                  setOpening(true);
                  openOwnCertificate(session, current.id)
                    .catch(setOpenError)
                    .finally(() => setOpening(false));
                }}
              >
                {opening ? "Opening…" : "View"}
              </button>
            )
          }
        />
      ) : (
        <p className="text-sm text-ink">
          {record.gst_registered === null
            ? "Save the business details first, so we know which certificate to ask for."
            : record.gst_registered
              ? "Upload the GST registration certificate."
              : "Upload the Certificate of Incorporation, or the Udyam registration certificate."}
        </p>
      )}
      {openError instanceof ViewerBlockedError ? (
        <p role="alert" className="mt-2 text-sm text-danger">
          {openError.message}
        </p>
      ) : (
        openError != null && (
          <div className="mt-2">
            <ProblemNotice error={openError} />
          </div>
        )
      )}
      {record.is_verified && current && (
        <p className={FIELD_HINT}>Your business is verified, so the certificate can no longer be changed.</p>
      )}
      {inReview && current && (
        <p className={FIELD_HINT}>It is with our review team, so it cannot be changed until the review is done.</p>
      )}
      {replaceable && record.gst_registered !== null && (
        <div className="mt-3 space-y-3">
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
    </Card>
  );
}

function ManualPath({ session, record, access }: { session: Session; record: KycRecord; access: Access }) {
  const upload = useUploadKycDocument(session);
  const submit = useSubmitForReview(session);
  const owner = record.documents.find((document) => document.slot === "owner_id" && document.held);
  const [number, setNumber] = useState("");
  const numberProblem = number ? panProblem(number) : null;

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
          className={FIELD}
          value={number}
          onChange={(event) => setNumber(event.target.value)}
          maxLength={10}
          autoComplete="off"
          aria-invalid={Boolean(numberProblem)}
        />
        <span className={FIELD_HINT}>We keep only a masked form, like XXXXX1234X.</span>
        {numberProblem && <span className="mt-1 block text-sm text-danger">{numberProblem}</span>}
      </label>
      <p className={FIELD_HINT}>
        The PAN card file is deleted as soon as our review is done, and after 30 days if it is not reviewed.
      </p>
      <button
        type="button"
        className={PRIMARY_BUTTON}
        disabled={!access.write.allowed || !owner || !number || Boolean(numberProblem) || submit.isPending}
        onClick={() => submit.mutate({ owner_id_type: "pan", owner_id_number: number.trim().toUpperCase() })}
      >
        Send for review
      </button>
      <ProblemNotice error={submit.error} />
    </div>
  );
}

function DigiLockerPath({ session, record, access }: { session: Session; record: KycRecord; access: WriteAccess }) {
  const start = useStartDigiLocker(session);
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
        name on it and a masked number — never the document.
      </p>
      <fieldset className="flex flex-wrap gap-4 text-sm text-ink">
        <legend className={FIELD_LABEL}>Which record to share</legend>
        <label className="flex items-center gap-2">
          <input type="radio" name="id-doc" checked={document === "aadhaar"} onChange={() => setDocument("aadhaar")} />
          Aadhaar
        </label>
        <label className="flex items-center gap-2">
          <input type="radio" name="id-doc" checked={document === "pan"} onChange={() => setDocument("pan")} />
          PAN
        </label>
      </fieldset>
      <button
        type="button"
        className={PRIMARY_BUTTON}
        disabled={!access.allowed || start.isPending || !record.entity_type}
        title={access.reason ?? undefined}
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
      </button>
      <ProblemNotice error={start.error} />
    </div>
  );
}

/** Finishes a run when the client comes back from DigiLocker. */
function DigiLockerReturn({ session }: { session: Session }) {
  const complete = useCompleteDigiLocker(session);
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
      <NoticeBox tone="warn" title="DigiLocker has not finished yet">
        <p className="mt-1">If you completed it, wait a moment and check again.</p>
        <button type="button" className={SECONDARY_BUTTON} onClick={() => complete.mutate(ref)}>
          Check again
        </button>
      </NoticeBox>
    );
  }
  const outcome = complete.data ? lookup(DIGILOCKER_OUTCOME, complete.data.status) : undefined;
  if (outcome) {
    return (
      <NoticeBox tone={outcome.tone} title={outcome.title}>
        <p className="mt-1">{outcome.body}</p>
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
