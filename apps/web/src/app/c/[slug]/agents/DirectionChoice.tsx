"use client";

/**
 * "Which way do this agent's calls go?" — asked the same way when an agent is built and
 * when it is changed.
 *
 * One component rather than two, because the two forms would otherwise drift in the place
 * it matters most: the three options ARE the server's `AgentDirection` literal, and a
 * fourth appearing on one screen and not the other is how a client comes to believe their
 * outbound agent cannot answer.
 *
 * A real `<input type="radio">` inside the label, visually hidden rather than replaced:
 * arrow keys move between the three, the group announces itself from its `<legend>`, and
 * what is painted is drawn from the input's own checked state so the two cannot disagree.
 * The same shape the campaign classification picker uses, which is what keeps this section
 * from introducing a second visual idiom.
 */

import { CheckCircle2, PhoneCall, PhoneIncoming, PhoneOutgoing } from "lucide-react";

import type { AgentDirection } from "@/lib/api/agents";

export interface DirectionOption {
  value: AgentDirection;
  label: string;
  hint: string;
  Icon: typeof PhoneCall;
}

/** The three directions the server's `AgentDirection` literal admits, in owner's words. */
export const DIRECTIONS: DirectionOption[] = [
  {
    value: "inbound",
    label: "Answer calls",
    hint: "Picks up when someone rings your number.",
    Icon: PhoneIncoming,
  },
  {
    value: "outbound",
    label: "Make calls",
    hint: "Dials your customers for campaigns and follow-ups.",
    Icon: PhoneOutgoing,
  },
  {
    value: "both",
    label: "Both",
    hint: "Picks up incoming calls and dials out too.",
    Icon: PhoneCall,
  },
];

/** The three cards. `name` scopes the radio group, so two on one page do not fight. */
export function DirectionPicker({
  name,
  value,
  onChange,
  disabled,
}: {
  name: string;
  value: AgentDirection;
  onChange: (next: AgentDirection) => void;
  disabled?: boolean;
}) {
  return (
    <div className="mt-2 grid gap-2 sm:grid-cols-3">
      {DIRECTIONS.map((option) => {
        const checked = option.value === value;
        return (
          <label
            key={option.value}
            className={`relative flex cursor-pointer flex-col rounded-card border p-3 transition-colors ${
              checked
                ? "border-brand bg-brand-soft"
                : "border-line bg-surface hover:bg-black/5 dark:hover:bg-white/5"
            }`}
          >
            <input
              type="radio"
              name={name}
              className="sr-only"
              checked={checked}
              disabled={disabled}
              onChange={() => onChange(option.value)}
            />
            {checked && (
              <CheckCircle2 aria-hidden className="absolute right-2 top-2 h-4 w-4 text-brand" />
            )}
            <option.Icon aria-hidden className="h-4 w-4 text-brand" />
            <span className="mt-2 block pr-6 text-sm font-semibold text-ink">{option.label}</span>
            <span className="mt-0.5 block text-xs text-ink-faint">{option.hint}</span>
          </label>
        );
      })}
    </div>
  );
}
