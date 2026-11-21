"use client";

/**
 * What an agent is for (founder, 21 Nov 2026): selling, or helping customers. A helping agent
 * never marks a caller interested from how pleased they sounded; the outcomes the owner set
 * still move callers as set. The server picks the first value from what the business does.
 */

import { CheckCircle2, LifeBuoy, ShoppingBag } from "lucide-react";

import { CHOICE_CARD, CHOICE_OFF, CHOICE_ON } from "@/components/console/choiceCard";
import type { Agent } from "@/lib/api/agents";

export type AgentPurpose = Agent["purpose"];

export const PURPOSES: { value: AgentPurpose; label: string; hint: string; Icon: typeof LifeBuoy }[] = [
  {
    value: "sales",
    label: "Selling",
    hint: "A caller who sounds keen is marked interested.",
    Icon: ShoppingBag,
  },
  {
    value: "support",
    label: "Helping customers",
    hint: "A happy caller is not counted as a sale.",
    Icon: LifeBuoy,
  },
];

export function PurposePicker({
  name,
  value,
  onChange,
  disabled,
}: {
  name: string;
  value: AgentPurpose;
  onChange: (next: AgentPurpose) => void;
  disabled?: boolean;
}) {
  return (
    <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
      {PURPOSES.map((option) => {
        const checked = option.value === value;
        return (
          <label key={option.value} className={`${CHOICE_CARD} ${checked ? CHOICE_ON : CHOICE_OFF}`}>
            <input
              type="radio"
              name={name}
              className="sr-only"
              checked={checked}
              disabled={disabled}
              onChange={() => onChange(option.value)}
            />
            {checked && <CheckCircle2 aria-hidden className="absolute right-2 top-2 h-4 w-4 text-brand-strong" />}
            <option.Icon aria-hidden className="block h-4 w-4 text-ink-muted" />
            <span className="mt-2 block pr-6 text-sm font-semibold text-ink">{option.label}</span>
            <span className="mt-0.5 block text-xs text-ink-muted">{option.hint}</span>
          </label>
        );
      })}
    </div>
  );
}
