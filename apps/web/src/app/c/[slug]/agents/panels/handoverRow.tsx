"use client";

import { ArrowDown, ArrowUp, Trash2 } from "lucide-react";

import { FIELD, FIELD_LABEL, QUIET_ICON_BUTTON, ToggleSwitch, formatPhone } from "@/components/ui";
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
    <li className="py-3.5">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 text-xs font-semibold text-ink-faint">{index + 1}</span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-ink" title={name}>
            {name}
          </p>
          {contact && (
            <p className="text-xs tabular-nums text-ink-muted">{formatPhone(contact.phone_e164)}</p>
          )}
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
      {/* One row: the switch, then the order and removal as quiet icons, so a list of five
          people does not read as five toolbars. Why "Available" exists is in How it works. */}
      <div className="mt-2 flex items-center justify-between gap-2 pl-6">
        <ToggleSwitch checked={row.active} onChange={(next) => onChange({ active: next })} label="Available" />
        <div className="flex items-center gap-0.5">
          <button
            type="button"
            className={QUIET_ICON_BUTTON}
            aria-label="Move up"
            title="Move up"
            disabled={index === 0}
            onClick={() => onMove(index - 1)}
          >
            <ArrowUp aria-hidden className="h-4 w-4" />
          </button>
          <button
            type="button"
            className={QUIET_ICON_BUTTON}
            aria-label="Move down"
            title="Move down"
            disabled={last}
            onClick={() => onMove(index + 1)}
          >
            <ArrowDown aria-hidden className="h-4 w-4" />
          </button>
          <button
            type="button"
            className={QUIET_ICON_BUTTON}
            aria-label={`Remove ${name}`}
            title="Remove"
            onClick={onRemove}
          >
            <Trash2 aria-hidden className="h-4 w-4" />
          </button>
        </div>
      </div>
    </li>
  );
}
