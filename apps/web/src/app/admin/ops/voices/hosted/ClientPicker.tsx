"use client";

import { FIELD, FIELD_HINT, FIELD_LABEL } from "@/components/ui";
import type { components } from "@/lib/api/schema";

export type ClientOption = components["schemas"]["ClientOptionOut"];

/**
 * A client with its own voice workspace, chosen by name: our keys are installed per client
 * workspace, and an operator should never have to copy an account id to name one. The list
 * is served with the card (`clients`), so it holds only clients an install can name.
 */
export function ClientPicker({
  id,
  label,
  clients,
  value,
  onChange,
  emptyLabel,
  hint,
  note,
}: {
  id: string;
  label: string;
  clients: ClientOption[];
  value: string;
  onChange: (tenantId: string) => void;
  /** The blank choice's words; it says what happens when no client is chosen. */
  emptyLabel: string;
  hint: string;
  /** A few words after a client's name, such as "on our key"; nothing when undefined. */
  note?: (tenantId: string) => string | undefined;
}) {
  return (
    <div className="mt-3">
      <label htmlFor={id} className={FIELD_LABEL}>
        {label}
      </label>
      <select id={id} className={`mt-1 ${FIELD}`} value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">{emptyLabel}</option>
        {clients.map((client) => {
          const extra = note?.(client.tenant_id);
          return (
            <option key={client.tenant_id} value={client.tenant_id}>
              {client.tenant_name ?? `Unnamed client (${client.tenant_id.slice(0, 8)})`}
              {extra ? ` · ${extra}` : ""}
            </option>
          );
        })}
      </select>
      <p className={FIELD_HINT}>{hint}</p>
      {clients.length === 0 && (
        <p className="mt-1 text-meta text-ink-muted">No client has a voice workspace of its own yet.</p>
      )}
    </div>
  );
}
