"use client";

import { Check } from "lucide-react";

import { CHOICE_CARD, CHOICE_OFF, CHOICE_ON } from "@/components/console/choiceCard";
import { InfoTip } from "@/components/console/infoTip";
import { FIELD, FIELD_LABEL } from "@/components/ui";
import { DEFAULT_RING_SECONDS, RING_SECONDS, type ForwardingMode } from "@/lib/api/forwarding";

import { MODE_COPY, RING_TIME_INFO } from "./copy";

/**
 * HOW CALLS REACH THE AGENT: two equal choices, each with what happens, and the ring time.
 *
 * The client chooses; nothing is preselected for them beyond the ring time's preset. The
 * ring time list includes 0 ("straight to your agent"): the carrier timer has no 0, so
 * picking it is picking "every call", and the codes shown switch with it.
 */
export function ModeChoice({
  mode,
  seconds,
  onChange,
  disabled = false,
  idPrefix = "forwarding",
}: {
  mode: ForwardingMode | null;
  seconds: number;
  onChange: (mode: ForwardingMode, seconds: number) => void;
  disabled?: boolean;
  idPrefix?: string;
}) {
  const choose = (next: ForwardingMode) =>
    onChange(next, next === "all_calls" ? 0 : seconds === 0 ? DEFAULT_RING_SECONDS : seconds);
  return (
    <div className="space-y-4">
      <fieldset className="space-y-2">
        <legend className="sr-only">How calls reach your agent</legend>
        {(["conditional", "all_calls"] as const).map((option) => {
          const on = mode === option;
          return (
            <label key={option} className={`${CHOICE_CARD} ${on ? CHOICE_ON : CHOICE_OFF}`}>
              <input
                type="radio"
                name={`${idPrefix}-mode`}
                value={option}
                checked={on}
                disabled={disabled}
                onChange={() => choose(option)}
                className="sr-only"
              />
              <span className="flex items-start justify-between gap-3">
                <span className="min-w-0">
                  <span className="block text-body font-medium text-ink">{MODE_COPY[option].title}</span>
                  <span className="mt-0.5 block text-meta text-ink-muted">{MODE_COPY[option].line}</span>
                </span>
                {on && <Check aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-brand-strong" />}
              </span>
            </label>
          );
        })}
      </fieldset>
      <div>
        <div className="flex items-center gap-1">
          <label htmlFor={`${idPrefix}-ring`} className={FIELD_LABEL}>
            How long your phone rings first
          </label>
          <InfoTip label="Ring time">{RING_TIME_INFO}</InfoTip>
        </div>
        <select
          id={`${idPrefix}-ring`}
          className={FIELD}
          disabled={disabled}
          value={mode === "all_calls" ? 0 : seconds}
          onChange={(event) => {
            const next = Number(event.target.value);
            onChange(next === 0 ? "all_calls" : "conditional", next);
          }}
        >
          <option value={0}>0 seconds: straight to your agent</option>
          {RING_SECONDS.map((value) => (
            <option key={value} value={value}>
              {value} seconds
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
