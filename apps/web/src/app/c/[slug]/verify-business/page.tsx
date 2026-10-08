"use client";

import { useEffect, useRef, useState } from "react";
import { CheckCircle2, ShieldAlert } from "lucide-react";

import { PageHeader } from "@/components/console/pageHeader";
import {
  Card,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON,
  Skeleton,
} from "@/components/ui";
import { ENTITY_TYPES, useKycRecord, type KycRecord } from "@/lib/api/kyc";
import { useClientSession } from "@/lib/api/session";
import type { Session } from "@/lib/api/client";
import {
  ACCEPT_ATTRIBUTE,
  BUSINESS_DOCUMENT_KINDS,
  GSTIN_PATTERN,
  OWNER_ID_KINDS,
  fileProblem,
  outboundSteps,
  ownerIdProblem,
  useAcceptPledge,
  useCompleteDigiLocker,
  useOutboundPledge,
  useSaveBusinessDetails,
  useStartDigiLocker,
  useSubmitForReview,
  useUploadKycDocument,
  type OutboundPledge,
} from "@/lib/api/verifyBusiness";

/** Where a started DigiLocker run's reference waits while the client is at DigiLocker. */
const PENDING_RUN_KEY = "calevate.kyc.pendingRun";

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
      {pledge.data && <PledgeCard session={session} pledge={pledge.data} />}
      {record && <VerifyCards session={session} record={record} />}
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

function PledgeCard({ session, pledge }: { session: Session; pledge: OutboundPledge }) {
  const accept = useAcceptPledge(session);
  const [read, setRead] = useState(false);
  return (
    <Card title="No-cold-calls pledge">
      <blockquote className="rounded-card border border-line bg-app p-4 text-sm text-ink">{pledge.pledge_text}</blockquote>
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
          <label className="flex items-start gap-2 text-sm text-ink">
            <input type="checkbox" checked={read} onChange={(event) => setRead(event.target.checked)} />
            I have read this and accept it on behalf of the business.
          </label>
          <button
            type="button"
            className={PRIMARY_BUTTON}
            disabled={!read || accept.isPending}
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

function VerifyCards({ session, record }: { session: Session; record: KycRecord }) {
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
      {!locked && <DetailsCard session={session} record={record} />}
      {!locked && <BusinessDocumentCard session={session} record={record} />}
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
                Upload the owner&apos;s ID for our review
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
          {path === "manual" && !record.digilocker_outstanding ? (
            <ManualPath session={session} record={record} />
          ) : (
            <DigiLockerPath session={session} record={record} />
          )}
        </Card>
      )}
    </>
  );
}

function DetailsCard({ session, record }: { session: Session; record: KycRecord }) {
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
          <button type="submit" className={PRIMARY_BUTTON} disabled={!ready || save.isPending}>
            Save details
          </button>
          {save.isSuccess && <span className="ml-3 text-sm text-ink">Saved.</span>}
          <ProblemNotice error={save.error} />
        </div>
      </form>
    </Card>
  );
}

function FilePicker({
  label,
  onPick,
}: {
  label: string;
  onPick: (file: File) => void;
}) {
  const [problem, setProblem] = useState<string | null>(null);
  return (
    <label className="block">
      <span className={FIELD_LABEL}>{label}</span>
      <input
        type="file"
        accept={ACCEPT_ATTRIBUTE}
        className="mt-1 block text-sm"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (!file) return;
          const why = fileProblem(file);
          setProblem(why);
          if (!why) onPick(file);
        }}
      />
      <span className={FIELD_HINT}>PDF, JPEG or PNG, up to 5 MB.</span>
      {problem && (
        <span role="alert" className="mt-1 block text-sm text-danger">
          {problem}
        </span>
      )}
    </label>
  );
}

function BusinessDocumentCard({ session, record }: { session: Session; record: KycRecord }) {
  const upload = useUploadKycDocument(session);
  const current = record.documents.find((document) => document.slot === "business");
  const options = record.gst_registered
    ? (["gst"] as const)
    : (["incorporation", "udyam"] as const);
  const [kind, setKind] = useState<string>(options[0]);
  return (
    <Card title="2. Business certificate">
      <p className="text-sm text-ink">
        {record.gst_registered === null
          ? "Save the business details first, so we know which certificate to ask for."
          : record.gst_registered
            ? "Upload the GST registration certificate."
            : "Upload the Certificate of Incorporation, or the Udyam registration certificate."}
      </p>
      {record.gst_registered !== null && (
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
          <FilePicker
            label={current ? `On file: ${current.filename}. Replace it` : "Choose the certificate"}
            onPick={(file) => upload.mutate({ slot: "business", kind: record.gst_registered ? "gst" : kind, file })}
          />
          {upload.isPending && <p className="text-sm text-ink-muted">Uploading…</p>}
          <ProblemNotice error={upload.error} />
        </div>
      )}
    </Card>
  );
}

function ManualPath({ session, record }: { session: Session; record: KycRecord }) {
  const upload = useUploadKycDocument(session);
  const submit = useSubmitForReview(session);
  const owner = record.documents.find((document) => document.slot === "owner_id" && document.held);
  const [kind, setKind] = useState<"aadhaar" | "pan_card">("pan_card");
  const [number, setNumber] = useState("");
  const idType = kind === "pan_card" ? "pan" : "aadhaar";
  const numberProblem = number ? ownerIdProblem(idType, number) : null;

  return (
    <div className="space-y-4">
      <label className="block">
        <span className={FIELD_LABEL}>Owner&apos;s ID</span>
        <select
          className={FIELD}
          value={kind}
          onChange={(event) => setKind(event.target.value === "aadhaar" ? "aadhaar" : "pan_card")}
        >
          {Object.entries(OWNER_ID_KINDS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      {kind === "aadhaar" && (
        <NoticeBox tone="warn" title="Upload the masked Aadhaar only">
          <p className="mt-1">
            Download the masked Aadhaar from UIDAI, where only the last four digits are visible. We reject an
            unmasked copy. To avoid uploading an Aadhaar at all, choose DigiLocker instead.
          </p>
        </NoticeBox>
      )}
      <FilePicker
        label={owner ? `On file: ${owner.filename}. Replace it` : "Choose the ID file"}
        onPick={(file) => upload.mutate({ slot: "owner_id", kind, file })}
      />
      <ProblemNotice error={upload.error} />
      <label className="block">
        <span className={FIELD_LABEL}>{idType === "pan" ? "PAN" : "Last four digits of the Aadhaar"}</span>
        <input
          className={FIELD}
          value={number}
          onChange={(event) => setNumber(event.target.value)}
          maxLength={idType === "pan" ? 10 : 4}
          inputMode={idType === "pan" ? "text" : "numeric"}
          autoComplete="off"
          aria-invalid={Boolean(numberProblem)}
        />
        <span className={FIELD_HINT}>
          {idType === "pan"
            ? "We keep only a masked form, like XXXXX1234X."
            : "Never type the full Aadhaar number. We keep XXXX-XXXX and these four digits."}
        </span>
        {numberProblem && <span className="mt-1 block text-sm text-danger">{numberProblem}</span>}
      </label>
      <p className={FIELD_HINT}>
        The ID file is deleted as soon as our review is done, and after 30 days if it is not reviewed.
      </p>
      <button
        type="button"
        className={PRIMARY_BUTTON}
        disabled={!owner || !number || Boolean(numberProblem) || submit.isPending}
        onClick={() => submit.mutate({ owner_id_type: idType, owner_id_number: number.trim().toUpperCase() })}
      >
        Send for review
      </button>
      <ProblemNotice error={submit.error} />
    </div>
  );
}

function DigiLockerPath({ session, record }: { session: Session; record: KycRecord }) {
  const start = useStartDigiLocker(session);
  const [document, setDocument] = useState<"aadhaar" | "pan">("aadhaar");
  if (!record.self_verification_available) {
    return (
      <p className="text-sm text-ink">
        DigiLocker verification is not available yet. Please upload the owner&apos;s ID for our review instead.
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
        disabled={start.isPending || !record.entity_type}
        onClick={() =>
          start.mutate(
            { entity_type: record.entity_type ?? "", id_document: document },
            {
              onSuccess: (run) => {
                try {
                  window.sessionStorage.setItem(PENDING_RUN_KEY, run.provider_ref);
                } catch {
                  // Storage blocked: the return leg still finishes from the provider's callback.
                }
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

  useEffect(() => {
    if (asked.current) return;
    asked.current = true;
    let stored: string | null = null;
    try {
      stored = window.sessionStorage.getItem(PENDING_RUN_KEY);
    } catch {
      stored = null;
    }
    const fromUrl = new URLSearchParams(window.location.search).get("provider_ref");
    const run = stored ?? fromUrl;
    if (!run) return;
    setRef(run);
    complete.mutate(run, {
      onSuccess: (result) => {
        if (result.status !== "pending") {
          try {
            window.sessionStorage.removeItem(PENDING_RUN_KEY);
          } catch {
            // Nothing to clean up.
          }
        }
      },
    });
  }, [complete]);

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
  return null;
}
