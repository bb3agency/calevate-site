"use client";

/**
 * Where Pip drafts the script fixes, for an agent that works on more than one Inbound line
 * or campaign (D-1017). Pip is told the one picked; with none picked it asks the owner.
 */

import { useId } from "react";

import { FIELD, FIELD_LABEL } from "@/components/ui";
import type { FixHolder } from "@/lib/api/script";

export function HolderPicker({
  holders,
  value,
  onChange,
}: {
  holders: readonly FixHolder[];
  value: string | null;
  onChange: (id: string | null) => void;
}) {
  const id = useId();
  return (
    <div className="w-full sm:w-64">
      <label htmlFor={id} className={FIELD_LABEL}>
        Script fixes go to
      </label>
      <select id={id} className={`${FIELD} touch:min-h-11`} value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
        <option value="">Choose a line or campaign</option>
        {holders.map((holder) => (
          <option key={holder.id} value={holder.id}>
            {holder.kind === "inbound_line" ? "Line" : "Campaign"}: {holder.name}
          </option>
        ))}
      </select>
    </div>
  );
}
