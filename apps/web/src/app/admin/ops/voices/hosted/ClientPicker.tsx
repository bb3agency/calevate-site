"use client";

import { Combobox } from "@/components/arc/combobox";
import type { components } from "@/lib/api/schema";

export type ClientOption = components["schemas"]["ClientOptionOut"];

/**
 * A client with its own voice workspace, chosen by name: our keys are installed per client
 * workspace, and an operator should never have to copy an account id to name one. The list
 * is served with the card (`clients`), so it holds only clients an install can name. A
 * combobox rather than a select because the list grows with paying clients (up to the
 * plan's 100 workspaces) and is found by typing a name.
 */
export function ClientPicker({
  label,
  clients,
  value,
  onChange,
  emptyLabel,
  hint,
  note,
}: {
  label: string;
  clients: ClientOption[];
  value: string;
  onChange: (tenantId: string) => void;
  /** Shown while no client is chosen; it says what happens when none is. */
  emptyLabel: string;
  hint: string;
  /** A few words after a client's name, such as "on our key"; nothing when undefined. */
  note?: (tenantId: string) => string | undefined;
}) {
  return (
    <div className="mt-3">
      <Combobox
        label={label}
        hint={hint}
        placeholder={emptyLabel}
        value={value || null}
        onChange={(next) => onChange(next ?? "")}
        options={clients.map((client) => ({
          value: client.tenant_id,
          label: client.tenant_name ?? `Unnamed client (${client.tenant_id.slice(0, 8)})`,
          hint: note?.(client.tenant_id),
        }))}
        emptyText={(query) =>
          clients.length === 0
            ? "No client has a voice workspace of its own yet."
            : `No client with a voice workspace matches “${query}”`
        }
      />
      {clients.length === 0 && (
        <p className="mt-1 text-meta text-ink-muted">No client has a voice workspace of its own yet.</p>
      )}
    </div>
  );
}
