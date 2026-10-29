"use client";

import { useId, useState } from "react";
import { Plus, X } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { Drawer } from "@/components/console/drawer";
import { FIELD_HINT, FIELD_LABEL, ProblemNotice, SECONDARY_BUTTON } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import {
  useSetLeadSourceConsentBasis,
  useSetLeadSourceMapping,
  type LeadSource,
} from "@/lib/api/leadSources";

import { rowName } from "./SourcesList";
import { hasFixedFields } from "./sourceKinds";
import { FIELD, QUIET_BUTTON } from "./styles";

/** Our three named fields; every other mapping entry is a detail the form sends. */
const NAMED = ["phone", "name", "consent_field"] as const;
/** The server's cap on mapping entries (`ingest/service.MAX_MAPPING_ENTRIES`). */
const MAX_ENTRIES = 50;

interface Extra {
  id: number;
  ours: string;
  theirs: string;
}

/**
 * WHICH FIELDS OF THE FORM THIS SOURCE READS, changed after it was made (D-893 L2).
 *
 * Opens on what the source reads now, so Save with nothing changed changes nothing. Every
 * box left empty means "send ours": a source with no names at all reads the form as it
 * comes. The phone is the one the server insists on once any name is given — without it
 * every lead would be refused — and it says so before the click rather than after.
 *
 * Leads already received keep what they were saved with; only new ones are read this way.
 */
export function FieldsDrawer({
  source,
  session,
  onClose,
}: {
  source: LeadSource;
  session: Session;
  onClose: () => void;
}) {
  const ids = useId();
  const save = useSetLeadSourceMapping(session);
  const saveBasis = useSetLeadSourceConsentBasis(session);
  const basisFeedback = useActionFeedback(saveBasis, { errorDisplay: "inline" });
  const feedback = useActionFeedback(save, { errorDisplay: "inline", successToast: "Saved" });
  const savedBasis = source.consent_basis === "application" ? "application" : "inquiry";
  const [basis, setBasis] = useState<"inquiry" | "application">(savedBasis);
  const current = source.mapping ?? {};
  const [phone, setPhone] = useState(current.phone ?? current.phone_number ?? "");
  const [name, setName] = useState(current.name ?? "");
  const [consent, setConsent] = useState(current.consent_field ?? "");
  const [extras, setExtras] = useState<Extra[]>(() =>
    Object.entries(current)
      .filter(([key]) => !(NAMED as readonly string[]).includes(key) && key !== "phone_number")
      .map(([ours, theirs], id) => ({ id, ours, theirs })),
  );
  const [nextId, setNextId] = useState(extras.length);

  const mapping: Record<string, string> = {};
  if (phone.trim()) mapping.phone = phone.trim();
  if (name.trim()) mapping.name = name.trim();
  if (consent.trim()) mapping.consent_field = consent.trim();
  for (const extra of extras) {
    if (extra.ours.trim() && extra.theirs.trim()) mapping[extra.ours.trim()] = extra.theirs.trim();
  }
  // A sender with a fixed, documented payload keeps its preset: only what the leads are is
  // chosen here, and the mapping is never written.
  const fixed = hasFixedFields(source.source);
  const named = Object.keys(mapping).length > 0;
  const missingPhone = !fixed && named && !mapping.phone;
  const half = !fixed && extras.some((e) => Boolean(e.ours.trim()) !== Boolean(e.theirs.trim()));
  const saveBasisThenClose = () =>
    basis === savedBasis
      ? onClose()
      : saveBasis.mutate({ webhookId: source.id, consentBasis: basis }, { onSuccess: onClose });

  const field = (label: string, value: string, onChange: (next: string) => void, hint: string, placeholder: string) => {
    const id = `${ids}-${label}`;
    return (
      <div className="min-w-0">
        <label htmlFor={id} className={FIELD_LABEL}>
          {label}
        </label>
        <input
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          maxLength={128}
          autoComplete="off"
          spellCheck={false}
          aria-describedby={`${id}-hint`}
          className={`${FIELD} mt-1 block w-full font-mono`}
        />
        <span id={`${id}-hint`} className={FIELD_HINT}>
          {hint}
        </span>
      </div>
    );
  };

  return (
    <Drawer
      open
      onClose={onClose}
      title={fixed ? "What these leads are" : "Fields your form sends"}
      description={rowName(source)}
      footer={
        <>
          <button type="button" onClick={onClose} className={SECONDARY_BUTTON}>
            Cancel
          </button>
          <ActionButton
            type="button"
            status={fixed ? basisFeedback.status : feedback.status}
            disabled={missingPhone || half}
            pendingLabel="Saving…"
            successLabel="Saved"
            onClick={() =>
              fixed
                ? saveBasisThenClose()
                : save.mutate({ webhookId: source.id, mapping }, { onSuccess: saveBasisThenClose })
            }
          >
            Save
          </ActionButton>
        </>
      }
    >
      <div className="space-y-4">
        {save.error && <ProblemNotice error={save.error} />}
        {saveBasis.error && <ProblemNotice error={saveBasis.error} />}
        {fixed ? (
          <p className="text-body text-ink">Fields are read automatically.</p>
        ) : (
          <>
            <p className="text-meta text-ink-muted">Your form&apos;s name for each field. Empty uses ours.</p>
            {field("Phone", phone, setPhone, "Needed whenever you name any field here.", "phone_number")}
            {missingPhone && (
              <p role="alert" className="-mt-2 text-meta text-danger">
                Name the phone field too, or leads are turned away.
              </p>
            )}
            {field("Name", name, setName, "The person's name.", "full_name")}
            {field(
              "Permission to call",
              consent,
              setConsent,
              "Optional. Leads who don't agree aren't called.",
              "consent_to_call",
            )}
          </>
        )}
        <fieldset className="space-y-1">
          <legend className={FIELD_LABEL}>What this form is</legend>
          {(
            [
              ["inquiry", "A question about you", "We may call for 7 days after it."],
              ["application", "An application (admission, loan, membership, job)", "We may call for 3 months after it."],
            ] as const
          ).map(([value, label, hint]) => (
            <label key={value} className="flex items-start gap-2 text-body text-ink">
              <input
                type="radio"
                name={`${ids}-basis`}
                value={value}
                checked={basis === value}
                onChange={() => setBasis(value)}
                className="mt-1"
              />
              <span>
                {label}
                <span className={FIELD_HINT}>{hint}</span>
              </span>
            </label>
          ))}
        </fieldset>

        {fixed ? null : (
        <fieldset className="space-y-2">
          <legend className={FIELD_LABEL}>Other details</legend>
          {extras.length === 0 && (
            <p className="text-meta text-ink-muted">None yet. Add one to keep another answer from the form.</p>
          )}
          <ul className="space-y-2">
            {extras.map((extra, index) => (
              <li key={extra.id} className="flex flex-wrap items-end gap-2 sm:flex-nowrap">
                <label className="block min-w-0 flex-1">
                  <span className="sr-only">Detail {index + 1}: our name</span>
                  <input
                    value={extra.ours}
                    onChange={(e) =>
                      setExtras(extras.map((x) => (x.id === extra.id ? { ...x, ours: e.target.value } : x)))
                    }
                    placeholder="our name, e.g. budget"
                    maxLength={128}
                    autoComplete="off"
                    spellCheck={false}
                    className={`${FIELD} block w-full font-mono`}
                  />
                </label>
                <span aria-hidden className="pb-2 text-ink-faint">
                  ←
                </span>
                <label className="block min-w-0 flex-1">
                  <span className="sr-only">Detail {index + 1}: your form&apos;s name</span>
                  <input
                    value={extra.theirs}
                    onChange={(e) =>
                      setExtras(extras.map((x) => (x.id === extra.id ? { ...x, theirs: e.target.value } : x)))
                    }
                    placeholder="your form's name"
                    maxLength={128}
                    autoComplete="off"
                    spellCheck={false}
                    className={`${FIELD} block w-full font-mono`}
                  />
                </label>
                <button
                  type="button"
                  onClick={() => setExtras(extras.filter((x) => x.id !== extra.id))}
                  aria-label={`Remove detail ${index + 1}`}
                  className={QUIET_BUTTON}
                >
                  <X aria-hidden className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
          {half && (
            <p role="alert" className="text-meta text-danger">
              Fill in both names for each detail, or remove it.
            </p>
          )}
          {extras.length + NAMED.length < MAX_ENTRIES && (
            <button
              type="button"
              onClick={() => {
                setExtras([...extras, { id: nextId, ours: "", theirs: "" }]);
                setNextId(nextId + 1);
              }}
              className={QUIET_BUTTON}
            >
              <Plus aria-hidden className="h-3.5 w-3.5" />
              Add a detail
            </button>
          )}
        </fieldset>
        )}
      </div>
    </Drawer>
  );
}
