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
 * - `action` is the quiet "Change" link of a label–value summary (REDESIGN-2). It sits
 *   after the value, so a settings summary reads "Calendar   Google · sri@…   Change".
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
  action,
  htmlFor,
  className = "",
}: {
  label: string;
  hint?: ReactNode;
  info?: ReactNode;
  value?: ReactNode;
  control?: ReactNode;
  /** A text action after the value (`TEXT_ACTION` from `console/section`). */
  action?: ReactNode;
  /** The id of the control, when it should be labelled by this row's label. */
  htmlFor?: string;
  className?: string;
}) {
  const Label = htmlFor ? "label" : "span";
  // A read-only fact (value, maybe a Change link) fits beside its label even on a phone;
  // only a row holding a form control stacks, so the control gets the full width.
  const layout = control
    ? "flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-6"
    : "flex-row flex-wrap items-center justify-between gap-x-6 gap-y-1";
  return (
    <div className={`flex py-3.5 ${layout} ${className}`}>
      <div className="min-w-0 sm:flex-1">
        <div className="flex items-center gap-1">
          <Label {...(htmlFor ? { htmlFor } : {})} className="text-body font-medium text-ink">
            {label}
          </Label>
          {info && <InfoTip label={label}>{info}</InfoTip>}
        </div>
        {hint && <p className="mt-0.5 text-meta text-ink-muted">{hint}</p>}
      </div>
      {(value !== undefined || control || action) && (
        <div className={`flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1 sm:max-w-[65%] sm:shrink-0 sm:justify-end sm:text-right ${control ? "" : "justify-end text-right"}`}>
          {value !== undefined && (
            <div className="min-w-0 text-body text-ink [overflow-wrap:anywhere]">{value}</div>
          )}
          {control}
          {action}
        </div>
      )}
    </div>
  );
}

/** A list of `SettingRow`s with hairlines between them. */
export function SettingRows({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`divide-y divide-line ${className}`}>{children}</div>;
}
