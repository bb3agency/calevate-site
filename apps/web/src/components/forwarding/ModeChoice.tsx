"use client";

import { ChoiceCards } from "@/components/console/choiceCards";
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
      <ChoiceCards
        legend="How calls reach your agent"
        legendClassName="sr-only"
        name={`${idPrefix}-mode`}
        value={mode}
        disabled={disabled}
        options={(["conditional", "all_calls"] as const).map((option) => ({
          value: option,
          label: MODE_COPY[option].title,
          hint: MODE_COPY[option].line,
        }))}
        onChange={choose}
      />
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
