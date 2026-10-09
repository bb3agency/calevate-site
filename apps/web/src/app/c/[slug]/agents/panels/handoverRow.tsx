"use client";

import { Trash2 } from "lucide-react";

import { FIELD, FIELD_LABEL, SECONDARY_BUTTON_SM, ToggleSwitch } from "@/components/ui";
import type { BusinessContact } from "@/lib/api/businessProfile";

import type { HandoverDraft } from "./handover";

/** One person on an agent's handover list: who they are (from the business profile),
 *  whether this agent may ring them now, and their place in the order. */
export function HandoverRow({
  row,
  index,
  last,
  contact,
  onChange,
  onMove,
  onRemove,
}: {
  row: HandoverDraft;
  index: number;
  last: boolean;
  contact: BusinessContact | undefined;
  onChange: (patch: Partial<HandoverDraft>) => void;
  onMove: (to: number) => void;
  onRemove: () => void;
}) {
  const name = contact?.label ?? "Someone since removed";
  return (
    <li className="rounded-lg border border-line p-3">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 text-xs font-semibold text-ink-faint">{index + 1}</span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-ink" title={name}>
            {name}
          </p>
          {contact && <p className="font-mono text-xs text-ink-muted">{contact.phone_e164}</p>}
          <label className="mt-2 block">
            <span className={FIELD_LABEL}>Note for this agent (optional)</span>
            <input
              className={FIELD}
              value={row.note}
              maxLength={500}
              placeholder="Ask for the manager first"
              onChange={(event) => onChange({ note: event.target.value })}
            />
          </label>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <ToggleSwitch
          checked={row.active}
          onChange={(next) => onChange({ active: next })}
          label="Available"
          hint="Switch off while they are away — they keep their place in the order."
        />
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          disabled={index === 0}
          onClick={() => onMove(index - 1)}
        >
          Move up
        </button>
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          disabled={last}
          onClick={() => onMove(index + 1)}
        >
          Move down
        </button>
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          aria-label={`Remove ${name}`}
          onClick={onRemove}
        >
          <Trash2 aria-hidden className="h-3.5 w-3.5" />
          Remove
        </button>
      </div>
    </li>
  );
}
