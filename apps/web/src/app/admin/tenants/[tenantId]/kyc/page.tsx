"use client";

import Link from "next/link";
import { use, useState } from "react";
import { AlertTriangle, ArrowLeft, CheckCircle2, FileWarning } from "lucide-react";

import {
  Card,
  EmptyState,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  TermGloss,
  formatIST,
} from "@/components/ui";
import { useRecordKyc, useTenant, useTenantKyc } from "@/lib/api/admin";
import {
  DOCUMENT_KINDS,
  ENTITY_TYPES,
  KYC_STATUS_COPY,
  asDocumentKind,
  asEntityType,
  documentKindLabel,
  entityTypeLabel,
  isKnownKycStatus,
  looksLikeAadhaar,
  recordBlockReason,
  type KycDocumentKind,
  type KycEntityType,
  type KycRecord,
  type KycRecordIn,
  type KycStatus,
} from "@/lib/api/kyc";

import { useAdminAccess } from "@/app/admin/access";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

/**
 * Recording a business's identity verification — R-11's last gate, and an audited write.
 *
 * `POST /v1/admin/tenants/{tenant_id}/kyc` shipped with no caller, which left the
 * refusals live and unclearable: a self-serve account blocked on `kyc_missing` stayed
 * blocked with nothing anyone could do about it. This is the form behind it.
 *
 * What a verification does NOT do is get anybody a phone number. Calevate does not
 * supply, sell or rent one: the client takes the connection in their own name on their
 * own Exotel / Plivo / Vobiz account and stays the subscriber of record (Model B —
 * `docs/legal/LEGAL-OPS-PLAYBOOK.md` §9, published Terms clause 3). This record exists
 * because their operator verifies the same entity we do, and our dial gate must not be
 * looser than the carrier's.
 *
 * Its own realm, and by permission rather than by preference. The write is
 * `admin:tenants` with the tenant named in the PATH — an admin-realm mutation that
 * inferred its tenant from the session would be un-callable under D-22 — and there is
 * deliberately no client-realm twin. What the client gets is the read.
 *
 * **Four questions an auditor asks, made un-skippable by the form and unfalsifiable by
 * the database.** `ck_kyc_records_verified_names_its_evidence` requires a `verified`
 * row to name the document kind, the document reference, the verifying admin and the
 * moment — and `ck_kyc_records_rejected_names_its_reason` requires a rejection to say
 * why. Two of those four are the operator's to supply and this form will not submit
 * without them; the other two are stamped server-side from the session and the database
 * clock, and are not fields here at all, because an operator who could type the date a
 * verification happened could type any date.
 *
 * The form is a preview of the refusal, never the enforcement. Every rule below is
 * enforced again by the route and again by a CHECK constraint underneath it.
 */
export default function TenantKycPage({
  params,
}: {
  // Next 15: `params` is a Promise in every page, unwrapped with React's `use()` in a
  // client component — nextjs.org/docs/app/api-reference/file-conventions/dynamic-routes.
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  const tenantQuery = useTenant(tenantId);
  const tenant = tenantQuery.data;
  const slug = tenant?.slug ?? "";
  // The mutation lives HERE, not in the form: a successful write invalidates the
  // record, the record comes back changed, and the form below is remounted by its key
  // to pick the new values up. A mutation held inside it would be remounted along with
  // it, and the confirmation of the write would vanish at the moment the write landed.
  const save = useRecordKyc(tenantId);
  // Read through impersonation, written through the admin surface: the D-22 split this
  // console already uses for the KB queue and the campaign prerequisites. Here it is
  // the only option — there is no admin-realm read of a tenant's KYC, because
  // `org:read` was chosen precisely so the state stays visible in a read-only session.
  const record = useTenantKyc(slug);
  // `POST /v1/admin/tenants/{id}/kyc` is `admin:tenants` (admin/routes.py). Disabled with
  // the reason beside it rather than a 403 after a form has been filled in — see
  // `@/app/admin/access` for why the client realm's `useWriteAccess` is the wrong
  // instrument on an admin screen.
  const write = useAdminAccess("admin:tenants", "record an identity verification");

  if (tenantQuery.isLoading) return <Skeleton rows={6} />;
  if (tenantQuery.error)
    return <ProblemNotice error={tenantQuery.error} onRetry={() => tenantQuery.refetch()} />;
  if (!tenant) return <EmptyState title="Client not found" />;

  return (
    <div className="max-w-3xl space-y-5">
      <div>
        <Link
          href={`/admin/tenants/${tenantId}`}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-strong hover:underline"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          {tenant.name}
        </Link>
        {/* Kept: `admin/layout.tsx` prints no page title, so this is the screen's only
            name. Delete it if one lands in the shell. */}
        <h1 className="mt-1 text-xl font-semibold text-ink">
          Identity verification (
          <TermGloss term="KYC">Know Your Customer — the business identity check</TermGloss>)
        </h1>
        <p className="text-sm text-ink-muted">
          The subscriber check behind a phone connection. A verified record opens number
          provisioning on every tier and outbound dialling on self-serve and trial
          accounts; inbound answering is never gated by it.
        </p>
      </div>

      {record.error && <ProblemNotice error={record.error} onRetry={() => record.refetch()} />}

      {record.isLoading ? (
        <Skeleton rows={4} />
      ) : !record.data ? (
        /* The form is withheld, not merely unpopulated, and the reason is worth saying
           on screen. `status` is the one field with no "leave as filed" option — the
           upsert assigns it outright — so recording from here while the current state is
           unreadable is a blind write over a state that might be an open verification.
           Closing a client's telecom gate by accident is a worse failure than making an
           operator retry a read. */
        <NoticeBox
          tone="warn"
          icon={<AlertTriangle className="h-5 w-5" />}
          title="Cannot record while the current state is unreadable"
        >
          <p className="mt-1 text-xs opacity-90">
            We could not read what is on file for this client. Recording a verification
            replaces the status outright, so doing it now could close a gate that is
            currently open without anyone seeing it happen. Retry the read above; the form
            comes back with it.
          </p>
        </NoticeBox>
      ) : (
        <>
          <OnFile record={record.data} />
          {/* Remounted only when the STORED record actually changes — a refetch that
              comes back identical keeps the same key and leaves whatever the operator
              is halfway through typing alone. Resetting via `key` rather than an effect
              is React's own answer to "reset state when a prop changes"
              (react.dev/learn/you-might-not-need-an-effect). */}
          <RecordForm
            key={recordStamp(record.data)}
            save={save}
            tenantName={tenant.name}
            record={record.data}
            write={write}
          />
          {save.error != null && <ProblemNotice error={save.error} />}
          {save.data && (
            <NoticeBox tone="ok" icon={<CheckCircle2 className="h-5 w-5" />}>
              <p className="text-xs">
                Recorded as <span className="font-medium">{save.data.status}</span>. The
                panel above has re-read what is now stored, and the client&apos;s own screen
                and their dial gate reflect it from the next request.
              </p>
            </NoticeBox>
          )}
        </>
      )}
    </div>
  );
}

/** Content, not identity: an equal refetch must not wipe a half-typed form. */
function recordStamp(record: KycRecord): string {
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
 * What is filed right now — read from the tenant's own view of it.
 *
 * Shown ABOVE the form and read from the server rather than echoed from the last write,
 * because `record_kyc` COALESCEs blank optional fields against the stored row: the
 * response to a write is what was sent, not what the record now says.
 */
function OnFile({ record }: { record: KycRecord }) {
  if (!record.recorded) {
    return (
      <NoticeBox tone="neutral" icon={<FileWarning className="h-5 w-5" />} title="Nothing on file">
        <p className="mt-1 text-xs opacity-90">
          The normal state of a new account. This client&apos;s dial gate reads it as a
          missing verification. Their own operator will ask for the same documents before
          it issues them a connection.
        </p>
      </NoticeBox>
    );
  }

  const status = record.status;
  const label = status !== null && isKnownKycStatus(status) ? KYC_STATUS_COPY[status].label : status;
  const rows: { label: string; value: string | null }[] = [
    { label: "Entity type", value: entityTypeLabel(record.entity_type) },
    { label: "Document", value: documentKindLabel(record.document_kind) },
    { label: "Reference", value: record.document_ref },
    { label: "Signatory", value: record.signatory_name },
    { label: "Evidence filed at", value: record.evidence_ref },
    { label: "Rejection reason", value: record.rejection_reason },
    { label: "Submitted", value: record.submitted_at ? formatIST(record.submitted_at) : null },
    { label: "Verified", value: record.verified_at ? formatIST(record.verified_at) : null },
  ].filter((row) => row.value !== null && row.value !== "");

  return (
    <Card
      title="On file"
      action={
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={
              record.is_verified
                ? "rounded-full bg-brand-strong px-2 py-0.5 text-xs font-medium text-white"
                : "rounded-full bg-brand-soft px-2 py-0.5 text-xs font-medium text-brand-strong"
            }
          >
            {label ?? "unknown"}
          </span>
          {/* The server's predicate, displayed and never recomputed. The dial gate, the
              purchase route and this badge must not be capable of disagreeing about
              whether `in_review` is good enough. */}
          <span className="text-xs text-ink-muted">
            {record.is_verified ? "gates open" : "gates closed"}
          </span>
        </div>
      }
    >
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

/** Every input on this form, in one place — the design language, not per-field taste. */
const FIELD =
  "w-full max-w-md rounded-md border border-line bg-surface px-2 py-1 text-xs text-ink placeholder:text-ink-faint disabled:cursor-not-allowed disabled:opacity-50 touch:min-h-11";

const STATUSES = Object.keys(KYC_STATUS_COPY) as KycStatus[];
const DOCUMENT_KIND_VALUES = Object.keys(DOCUMENT_KINDS) as KycDocumentKind[];
const ENTITY_TYPE_VALUES = Object.keys(ENTITY_TYPES) as KycEntityType[];

/**
 * The write itself.
 *
 * Prefilled from the stored record, which is both the kinder form and the safer one:
 * the endpoint upserts with COALESCE, so a blank optional field leaves the filed value
 * in place rather than clearing it. `rejection_reason` is the exception — it is
 * assigned outright, so blanking it really does clear it — and that is stated on screen
 * rather than left to be discovered.
 */
function RecordForm({
  save,
  tenantName,
  record,
  write,
}: {
  save: ReturnType<typeof useRecordKyc>;
  tenantName: string;
  record: KycRecord;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const [draft, setDraft] = useState<KycRecordIn>(() => initialDraft(record));

  const set = <K extends keyof KycRecordIn>(key: K, value: KycRecordIn[K]) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
    save.reset();
  };

  /*
   * THE KYC RECORD, DECLARED TO THE SCREEN ASSISTANT.
   *
   * One typed draft, so the fill is one `setDraft` — never the DOM. It is NOT built with
   * `flatDraftSurface` (the helper the two other admin record forms use) because every
   * member here is `string | null` and the difference between `null` and `""` is the
   * difference between "not recorded" and "recorded as blank" on a compliance row. The
   * conversion is therefore explicit in both directions, once, here.
   *
   * `signatory_name` is the ONE personal value on this form: the entity identifiers are
   * about a BUSINESS (`lib/api/kyc.ts` makes the same point — "none identifies a natural
   * person"), and the signatory is a named human, so it leaves as «NAME_1».
   *
   * `setDraft` and not `set`: `set` clears the refusal on screen, which a fill must not.
   */
  useCopilotSurface({
    route: "/admin/tenants/{id}/kyc",
    title: "Client KYC record",
    realm: "admin",
    fields: [
      {
        id: "kyc-status",
        label: "Status",
        type: "select",
        value: draft.status,
        options: STATUSES.map((value) => ({ value, label: KYC_STATUS_COPY[value].label })),
      },
      {
        id: "kyc-entity",
        label: "Entity type",
        type: "select",
        value: draft.entity_type ?? "",
        options: ENTITY_TYPE_VALUES.map((value) => ({ value, label: ENTITY_TYPES[value] })),
        help: 'Empty means not recorded.',
      },
      {
        id: "kyc-doc-kind",
        label: "Document kind",
        type: "select",
        value: draft.document_kind ?? "",
        options: DOCUMENT_KIND_VALUES.map((value) => ({
          value,
          label: DOCUMENT_KINDS[value].label,
        })),
      },
      {
        id: "kyc-doc-ref",
        label: "Document reference",
        type: "text",
        value: draft.document_ref ?? "",
        help: "The identifier printed on the document itself. Up to 64 characters.",
      },
      {
        id: "kyc-signatory",
        label: "Authorised signatory",
        type: "text",
        value: draft.signatory_name ?? "",
        personal: "name",
      },
      {
        id: "kyc-evidence",
        label: "Evidence reference",
        type: "text",
        value: draft.evidence_ref ?? "",
      },
      {
        id: "kyc-rejection",
        label: "Rejection reason",
        type: "textarea",
        value: draft.rejection_reason ?? "",
        help: "Shown to the client. Only meaningful while the status is rejected.",
      },
    ],
    facts: [{ key: "tenant", label: "Client", value: tenantName }],
    apply: (items) => {
      const next = { ...draft };
      for (const item of items) {
        // `""` back to `null` on every optional member: an empty string here would
        // record "we looked and there is nothing", which is a different compliance
        // claim from "nobody has recorded this yet".
        // `asText` first, because the wire value is typed to the FIELD and every member
        // of this draft is `string | null` — a screen that takes the union straight would
        // be the only one in the tree deciding what a boolean means on a compliance row.
        const text = asText(item.value);
        const blankToNull = text.trim() === "" ? null : text;
        if (item.field_id === "kyc-status" && isKnownKycStatus(text)) next.status = text;
        else if (item.field_id === "kyc-entity") next.entity_type = asEntityType(blankToNull);
        else if (item.field_id === "kyc-doc-kind") next.document_kind = asDocumentKind(blankToNull);
        else if (item.field_id === "kyc-doc-ref") next.document_ref = blankToNull;
        else if (item.field_id === "kyc-signatory") next.signatory_name = blankToNull;
        else if (item.field_id === "kyc-evidence") next.evidence_ref = blankToNull;
        else if (item.field_id === "kyc-rejection") next.rejection_reason = blankToNull;
      }
      setDraft(next);
    },
  });

  /**
   * The status decides whether the rejection reason means anything, so it clears it.
   *
   * That field is assigned OUTRIGHT by the upsert rather than COALESCEd. Without this,
   * switching a rejected record to `verified` would carry the old refusal into the new
   * row and show it to the client under a status it does not explain — and the box it
   * was typed in is no longer on screen to notice it in.
   */
  const chooseStatus = (next: KycStatus) => {
    setDraft((prev) => ({
      ...prev,
      status: next,
      rejection_reason: next === "rejected" ? prev.rejection_reason : null,
    }));
    save.reset();
  };

  const blocked = recordBlockReason(draft);
  const aadhaarTyped = looksLikeAadhaar(draft.document_ref);
  // The empty option means "send null", and null means two different things depending
  // on whether there is a row to leave alone. Saying "leave as filed" over an account
  // with nothing filed would describe a behaviour that is not happening.
  const unsetLabel = record.recorded ? "— leave as filed —" : "— not recorded —";

  return (
    <Card title="Record a verification">
      <p className="-mt-2 text-xs text-ink-muted">
        Saving here records or updates the check — re-recording is what happens on every
        re-verification, and moving off <span className="font-mono">verified</span> clears
        the verification date and the verifier with it.
      </p>

      <form
        className="mt-4 space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate(draft);
        }}
      >
        <RestrictionNote reason={write.reason} />
        <Field label="Status" htmlFor="kyc-status" hint="What this check concluded.">
          <select
            id="kyc-status"
            value={draft.status}
            disabled={!write.allowed}
            onChange={(e) => chooseStatus(e.target.value as KycStatus)}
            className={FIELD}
          >
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {KYC_STATUS_COPY[value].operator}
              </option>
            ))}
          </select>
        </Field>

        <Field
          label="Entity type"
          htmlFor="kyc-entity"
          hint="What kind of business this is, as registered."
        >
          <select
            id="kyc-entity"
            value={draft.entity_type ?? ""}
            disabled={!write.allowed}
            onChange={(e) => set("entity_type", (e.target.value || null) as KycEntityType | null)}
            className={FIELD}
          >
            <option value="">{unsetLabel}</option>
            {ENTITY_TYPE_VALUES.map((value) => (
              <option key={value} value={value}>
                {ENTITY_TYPES[value]}
              </option>
            ))}
          </select>
        </Field>

        <Field
          label="Document checked"
          htmlFor="kyc-doc-kind"
          hint={
            draft.document_kind
              ? DOCUMENT_KINDS[draft.document_kind].hint
              : "Which register the business was verified against. Entity registries only — there is no member here that identifies a person."
          }
        >
          <select
            id="kyc-doc-kind"
            value={draft.document_kind ?? ""}
            disabled={!write.allowed}
            onChange={(e) =>
              set("document_kind", (e.target.value || null) as KycDocumentKind | null)
            }
            className={FIELD}
          >
            <option value="">{unsetLabel}</option>
            {DOCUMENT_KIND_VALUES.map((value) => (
              <option key={value} value={value}>
                {DOCUMENT_KINDS[value].label}
              </option>
            ))}
          </select>
        </Field>

        <Field
          label="Registry number"
          htmlFor="kyc-doc-ref"
          hint="The public identifier from that register. Never an Aadhaar or an individual's PAN — the database refuses one, and it must not reach us in the first place."
        >
          <input
            id="kyc-doc-ref"
            value={draft.document_ref ?? ""}
            disabled={!write.allowed}
            onChange={(e) => set("document_ref", e.target.value)}
            maxLength={64}
            autoComplete="off"
            placeholder={
              draft.document_kind ? DOCUMENT_KINDS[draft.document_kind].placeholder : "CIN, GSTIN, LLPIN…"
            }
            className={
              aadhaarTyped
                ? `font-mono border-rose-500 dark:border-rose-700 ${FIELD}`
                : `font-mono ${FIELD}`
            }
          />
        </Field>

        <Field
          label="Signatory"
          htmlFor="kyc-signatory"
          hint="Who signed for the entity. A name only — their identity document stays with the licensee's CAF and is never recorded here."
        >
          <input
            id="kyc-signatory"
            value={draft.signatory_name ?? ""}
            disabled={!write.allowed}
            onChange={(e) => set("signatory_name", e.target.value)}
            maxLength={200}
            autoComplete="off"
            className={FIELD}
          />
        </Field>

        <Field
          label="Evidence reference"
          htmlFor="kyc-evidence"
          hint="Where the verification pack is filed — a ticket id or an object key. A reference, never the document."
        >
          <input
            id="kyc-evidence"
            value={draft.evidence_ref ?? ""}
            disabled={!write.allowed}
            onChange={(e) => set("evidence_ref", e.target.value)}
            maxLength={200}
            autoComplete="off"
            className={FIELD}
          />
        </Field>

        {/* Only where it means something. A rejection reason carried over from a past
            refusal onto a `verified` row would be an explanation of nothing, and the
            field is assigned outright rather than COALESCEd — so it is also the one
            box where leaving it blank genuinely clears what is filed. */}
        {draft.status === "rejected" && (
          <Field
            label="Why it was rejected"
            htmlFor="kyc-rejection"
            hint="Required. Goes to the client verbatim on their own screen, so write it to them: what was missing or wrong, and what to send instead."
          >
            <textarea
              id="kyc-rejection"
              rows={3}
              maxLength={500}
              value={draft.rejection_reason ?? ""}
              disabled={!write.allowed}
              onChange={(e) => set("rejection_reason", e.target.value)}
              className={FIELD}
            />
          </Field>
        )}

        {/* The destructive direction, called out where it is decided. Moving a live
            verification to anything else clears `verified_at` and the verifier and
            closes the gates behind them — a consequence that is obvious when you mean
            it and invisible when you have picked the wrong row. */}
        {record.is_verified && draft.status !== "verified" && (
          <NoticeBox tone="warn" icon={<AlertTriangle className="h-4 w-4" />}>
            <p className="text-xs">
              <span className="font-medium">{tenantName} is verified today.</span> Recording
              this stops outbound dialling on a self-serve or trial account, on every tier.
              Inbound answering is unaffected either way.
            </p>
          </NoticeBox>
        )}

        <WillRecord draft={draft} tenantName={tenantName} />

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={save.isPending || blocked !== null || !write.allowed}
            className="rounded-md bg-brand-strong px-3 py-1.5 text-xs font-semibold text-white hover:bg-brand-deep disabled:cursor-not-allowed disabled:opacity-50"
          >
            {save.isPending ? "Recording…" : "Record verification"}
          </button>
          {/* The refusal, given before the click rather than as a 422 — or, for the two
              rules the route does not pre-empt, before a 500 out of an IntegrityError. */}
          {blocked && (
            <span className="text-xs text-amber-700 dark:text-amber-400">{blocked}</span>
          )}
        </div>
      </form>
    </Card>
  );
}

/**
 * What this write will actually put in the record, said before it is made.
 *
 * The two facts an auditor most needs are the two the operator cannot supply: the
 * verifying admin comes from the session that sends this request, and the timestamp
 * from the database in the same statement. Stating that here is the point — it is why
 * there is no "verified on" date picker on this form and why nobody should go looking
 * for one.
 */
function WillRecord({ draft, tenantName }: { draft: KycRecordIn; tenantName: string }) {
  const verified = draft.status === "verified";
  return (
    <div className="rounded-card border border-line bg-app p-3 text-xs text-ink-muted">
      <p className="font-medium text-ink">This will record, against {tenantName}:</p>
      <ul className="mt-1.5 space-y-1">
        <li>
          <span className="text-ink-faint">Outcome</span> —{" "}
          {KYC_STATUS_COPY[draft.status].label.toLowerCase()}
          {verified && ", which clears the identity gate on every tier and opens outbound dialling on self-serve and trial accounts"}
          .
        </li>
        <li>
          <span className="text-ink-faint">Checked against</span> —{" "}
          {draft.document_kind
            ? `${DOCUMENT_KINDS[draft.document_kind].label} ${(draft.document_ref ?? "").trim() || "(no reference yet)"}`
            : "nothing named yet; blank leaves whatever is already filed"}
          .
        </li>
        <li>
          <span className="text-ink-faint">Verified by</span> — the admin account sending
          this request. Taken from your session, not from this form.
        </li>
        <li>
          <span className="text-ink-faint">Verified at</span> —{" "}
          {verified
            ? "stamped by the database as this row is written."
            : "cleared, because this is not a verified record."}
        </li>
        <li>
          <span className="text-ink-faint">Audit</span> — one audit-log entry with the
          status and the registry reference. The signatory&apos;s name is deliberately not
          copied into it.
        </li>
      </ul>
      <p className="mt-2 text-ink-muted">
        Blank optional fields leave what is already filed alone; only the rejection reason
        is replaced outright.
      </p>
    </div>
  );
}

/**
 * The form's starting point: what is filed, or a fresh record.
 *
 * `status` falls back to `submitted` rather than `verified` when the stored value is a
 * member this build does not know — a default that opens the telecom gate is not a
 * default worth having.
 */
function initialDraft(record: KycRecord): KycRecordIn {
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

function Field({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label
        htmlFor={htmlFor}
        className="text-xs font-semibold uppercase tracking-wide text-ink-muted"
      >
        {label}
      </label>
      <div className="mt-1">{children}</div>
      <p className="mt-1 max-w-md text-xs text-ink-muted">{hint}</p>
    </div>
  );
}
