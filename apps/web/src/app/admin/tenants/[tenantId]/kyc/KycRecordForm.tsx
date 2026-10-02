"use client";

import { useState, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";

import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  RestrictionNote,
} from "@/components/ui";
import type { useAdminAccess } from "@/app/admin/access";
import type { useRecordKyc } from "@/lib/api/admin";
import {
  DOCUMENT_KINDS,
  ENTITY_TYPES,
  KYC_STATUS_COPY,
  asDocumentKind,
  asEntityType,
  isKnownKycStatus,
  looksLikeAadhaar,
  recordBlockReason,
  type KycDocumentKind,
  type KycEntityType,
  type KycRecord,
  type KycRecordIn,
  type KycStatus,
} from "@/lib/api/kyc";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

import { initialDraft } from "./kycDraft";

const STATUSES = Object.keys(KYC_STATUS_COPY) as KycStatus[];
const DOCUMENT_KIND_VALUES = Object.keys(DOCUMENT_KINDS) as KycDocumentKind[];
const ENTITY_TYPE_VALUES = Object.keys(ENTITY_TYPES) as KycEntityType[];

/**
 * Recording our identity verdict. Four questions an auditor asks are un-skippable here and
 * unfalsifiable underneath: `ck_kyc_records_verified_names_its_evidence` requires a
 * verified row to name the document kind, the reference, the verifier and the moment, and a
 * rejection must say why. The verifier and the moment are stamped server-side from the
 * session and the database clock — never fields — because an operator who could type the
 * date of a verification could type any date. The form previews the refusal; the route and
 * the CHECK enforce it.
 */
export function KycRecordForm({
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
   * One typed draft, filled with one `setDraft`. Not `flatDraftSurface`: every member is
   * `string | null`, and `null` versus `""` is "not recorded" versus "recorded as blank" on
   * a compliance row, so the conversion is explicit, here, once. `signatory_name` is the one
   * value about a natural person and leaves as «NAME_1». `setDraft`, not `set`, because
   * `set` clears the refusal on screen and a fill must not.
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
        help: "Empty means not recorded.",
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
        // `""` back to `null`: an empty string would record "we looked and there is
        // nothing", a different compliance claim from "nobody has recorded this yet".
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
   * The status decides whether the rejection reason means anything, so it clears it. That
   * field is assigned OUTRIGHT by the upsert, so without this a rejected record switched to
   * verified would carry the old refusal to the client under a status it does not explain.
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
  // The empty option sends null, and null means "leave as filed" only if a row exists.
  const unsetLabel = record.recorded ? "— leave as filed —" : "— not recorded —";

  return (
    <form
      className="max-w-xl space-y-4"
      // No rule here the browser can refuse beyond `maxLength`; our own refusals are written
      // beside each control, and `noValidate` keeps a later rule out of the browser's words.
      noValidate
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

      <Field label="Entity type" htmlFor="kyc-entity" hint="What kind of business this is, as registered.">
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
          onChange={(e) => set("document_kind", (e.target.value || null) as KycDocumentKind | null)}
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
          aria-invalid={aadhaarTyped || undefined}
          className={`${FIELD} font-mono`}
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

      {/* Only where it means something; it is also the one field where blank really clears
          what is filed, because the upsert assigns it outright. */}
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

      {/* The destructive direction, said where it is decided: obvious when meant, invisible
          when the wrong row was picked. */}
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
          className={`${PRIMARY_BUTTON} max-sm:w-full max-sm:justify-center`}
        >
          {save.isPending ? "Recording…" : "Record verification"}
        </button>
        {/* The refusal before the click rather than a 422 — or, for the two rules the
            route does not pre-empt, a 500 out of an IntegrityError. */}
        {blocked && <span className="text-xs text-warn">{blocked}</span>}
      </div>
    </form>
  );
}

/** What this write will put in the record, said before it is made. */
function WillRecord({ draft, tenantName }: { draft: KycRecordIn; tenantName: string }) {
  const verified = draft.status === "verified";
  return (
    <div className="rounded-card border border-line bg-app p-3 text-xs text-ink-muted">
      <p className="font-medium text-ink">This will record, against {tenantName}:</p>
      <ul className="mt-1.5 space-y-1">
        <li>
          <span className="text-ink-faint">Outcome</span> —{" "}
          {KYC_STATUS_COPY[draft.status].label.toLowerCase()}
          {verified
            ? ", which clears the identity gate on every tier and opens outbound dialling on self-serve and trial accounts."
            : ". Any verification date and verifier on file are cleared."}
        </li>
        <li>
          <span className="text-ink-faint">Checked against</span> —{" "}
          {draft.document_kind
            ? `${DOCUMENT_KINDS[draft.document_kind].label} ${(draft.document_ref ?? "").trim() || "(no reference yet)"}.`
            : "nothing named yet; blank leaves whatever is already filed."}
        </li>
        <li>
          <span className="text-ink-faint">Verified by</span> — the admin account sending this
          request. Taken from your session, not from this form.
          {verified && " The time is stamped by the database."}
        </li>
        <li>
          <span className="text-ink-faint">Audit</span> — one entry with the status and the
          registry reference; the signatory&apos;s name is not copied into it. Blank optional
          fields leave what is filed alone; only the rejection reason is replaced outright.
        </li>
      </ul>
    </div>
  );
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
  children: ReactNode;
}) {
  return (
    <div>
      <label htmlFor={htmlFor} className={FIELD_LABEL}>
        {label}
      </label>
      {children}
      <span className={FIELD_HINT}>{hint}</span>
    </div>
  );
}
