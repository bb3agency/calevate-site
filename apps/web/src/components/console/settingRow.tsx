import type { ReactNode } from "react";

import { InfoTip } from "./infoTip";

/**
 * ONE SETTING ON ONE LINE: its name (and an ⓘ for the reasoning) on the left, its value
 * or its control on the right. Rows stack into a list with hairlines between them, so a
 * settings section reads as a table of facts rather than a stack of cards.
 *
 * - `hint` is one short line under the label. Anything longer goes in `info`.
 * - Pass `value` for a read-only fact, `control` for a switch / select / button. Give a
 *   form control its own accessible name (`aria-label` or an id + `htmlFor`); this row's
 *   label is visual, so a bare control inside it would be unnamed.
 * - Below `sm` the control drops under the label, full width, so nothing is squeezed.
 *
 * Compose rows inside a `<SettingRows>` (or any element with `divide-y divide-line`).
 */
export function SettingRow({
  label,
  hint,
  info,
  value,
  control,
  htmlFor,
  className = "",
}: {
  label: string;
  hint?: ReactNode;
  info?: ReactNode;
  value?: ReactNode;
  control?: ReactNode;
  /** The id of the control, when it should be labelled by this row's label. */
  htmlFor?: string;
  className?: string;
}) {
  const Label = htmlFor ? "label" : "span";
  return (
    <div className={`flex flex-col gap-2 py-3.5 sm:flex-row sm:items-center sm:justify-between sm:gap-6 ${className}`}>
      <div className="min-w-0 sm:flex-1">
        <div className="flex items-center gap-1">
          <Label {...(htmlFor ? { htmlFor } : {})} className="text-[14px] font-medium text-ink">
            {label}
          </Label>
          {info && <InfoTip label={label}>{info}</InfoTip>}
        </div>
        {hint && <p className="mt-0.5 text-[13px] text-ink-muted">{hint}</p>}
      </div>
      {(value !== undefined || control) && (
        <div className="min-w-0 sm:max-w-[60%] sm:shrink-0 sm:text-right">
          {value !== undefined && <div className="text-[14px] text-ink">{value}</div>}
          {control}
        </div>
      )}
    </div>
  );
}

/** A list of `SettingRow`s with hairlines between them. */
export function SettingRows({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`divide-y divide-line ${className}`}>{children}</div>;
}
