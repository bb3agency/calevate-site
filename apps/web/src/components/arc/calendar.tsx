"use client";

/**
 * THE date controls: `Calendar` (the month grid), `DatePicker` (one day) and
 * `DateRangePicker` (a span of days, with presets). Adapted from uiarc's `calendar`,
 * `date-picker` and `date-range-picker` (MIT, see ./LICENSE).
 *
 * What changed from Arc, and why:
 * - Every date is an IST calendar day "YYYY-MM-DD" and "today" is the day it is in India
 *   (`ist-dates.ts`), not the device's day: Arc read the browser clock, which is a day out
 *   for a colleague abroad and for everyone in the small hours under "view as client".
 * - The week starts on Monday and names are en-IN.
 * - Keyboard follows the APG date-picker grid: arrows move a day or a week, Home/End go to
 *   the week's ends, PageUp/PageDown a month (Shift: a year), Enter or Space picks.
 * - Day cells are 44px under a coarse pointer; the slide between months is dropped (a
 *   keyboard user pages months quickly and the slide only delays the grid).
 *
 * The pickers open in the kit popover, which flips and shifts to stay on a phone's screen.
 */

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { CalendarDays, ChevronLeft, ChevronRight, X } from "lucide-react";
import clsx from "clsx";

import { Field, FIELD_FLUSH } from "./field";
import { Popover } from "./popover";
import {
  addDays,
  addMonths,
  compareDates,
  endOfMonth,
  formatDateLong,
  formatDateRange,
  formatDateShort,
  formatMonth,
  monthGrid,
  startOfMonth,
  todayIST,
  weekdayIndex,
  weekdayNames,
  type ISODate,
} from "./ist-dates";

export type DateRange = { start: ISODate; end: ISODate };

export type CalendarProps = {
  /** The picked day (single), or the picked span (range); null for none. */
  selected: ISODate | DateRange | null;
  onSelect: (day: ISODate) => void;
  min?: ISODate;
  max?: ISODate;
  isDisabled?: (day: ISODate) => boolean;
  /** Which month opens first. Default: the selection's month, else today's. */
  initialMonth?: ISODate;
  /** While a range's second day is being chosen, the first one, for the hover preview. */
  rangeAnchor?: ISODate | null;
  /** Accessible name of the grid. */
  label?: string;
  previousMonthLabel?: string;
  nextMonthLabel?: string;
  todayLabel?: string;
  /** Move focus into the grid on mount (when it opens in a popover). */
  focusOnMount?: boolean;
};

function within(day: ISODate, min?: ISODate, max?: ISODate): boolean {
  return (!min || day >= min) && (!max || day <= max);
}

export function Calendar({
  selected,
  onSelect,
  min,
  max,
  isDisabled,
  initialMonth,
  rangeAnchor = null,
  label = "Choose a date",
  previousMonthLabel = "Previous month",
  nextMonthLabel = "Next month",
  todayLabel = "today",
  focusOnMount = false,
}: CalendarProps) {
  const today = useMemo(() => todayIST(), []);
  const selectedStart = selected === null ? null : typeof selected === "string" ? selected : selected.start;
  const [focus, setFocus] = useState<ISODate>(() => initialMonth ?? selectedStart ?? today);
  const [hover, setHover] = useState<ISODate | null>(null);
  const grid = useMemo(() => monthGrid(focus), [focus]);
  const names = useMemo(() => weekdayNames(), []);
  const cells = useRef(new Map<ISODate, HTMLButtonElement>());
  const moved = useRef(focusOnMount);

  // Keyboard moves focus with the roving day; a click or a re-render does not steal it.
  useEffect(() => {
    if (!moved.current) return;
    moved.current = false;
    cells.current.get(focus)?.focus();
  }, [focus]);

  const disabled = (day: ISODate) => !within(day, min, max) || Boolean(isDisabled?.(day));
  const go = (day: ISODate) => {
    const held = min && day < min ? min : max && day > max ? max : day;
    moved.current = true;
    setFocus(held);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, day: ISODate) => {
    const moves: Record<string, () => ISODate> = {
      ArrowLeft: () => addDays(day, -1),
      ArrowRight: () => addDays(day, 1),
      ArrowUp: () => addDays(day, -7),
      ArrowDown: () => addDays(day, 7),
      Home: () => addDays(day, -weekdayIndex(day)),
      End: () => addDays(day, 6 - weekdayIndex(day)),
      PageUp: () => addMonths(day, event.shiftKey ? -12 : -1),
      PageDown: () => addMonths(day, event.shiftKey ? 12 : 1),
    };
    const move = moves[event.key];
    if (move) {
      event.preventDefault();
      go(move());
    }
  };

  const range =
    selected !== null && typeof selected !== "string"
      ? selected
      : rangeAnchor && hover
        ? { start: compareDates(rangeAnchor, hover) <= 0 ? rangeAnchor : hover, end: compareDates(rangeAnchor, hover) <= 0 ? hover : rangeAnchor }
        : null;
  const monthStart = startOfMonth(focus);
  const canBack = !min || addDays(monthStart, -1) >= min;
  const canForward = !max || addMonths(monthStart, 1) <= max;
  const navButton =
    "grid h-8 w-8 place-items-center rounded-md text-ink-muted hover:bg-ink/[0.05] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:text-ink-faint disabled:hover:bg-transparent touch:h-11 touch:w-11";

  return (
    <div className="w-full min-w-0 select-none">
      <div className="mb-2 flex items-center justify-between gap-2">
        <button type="button" className={navButton} aria-label={previousMonthLabel} disabled={!canBack} onClick={() => setFocus(addMonths(focus, -1))}>
          <ChevronLeft aria-hidden className="h-4 w-4" />
        </button>
        <p aria-live="polite" className="text-body font-semibold text-ink">
          {formatMonth(focus)}
        </p>
        <button type="button" className={navButton} aria-label={nextMonthLabel} disabled={!canForward} onClick={() => setFocus(addMonths(focus, 1))}>
          <ChevronRight aria-hidden className="h-4 w-4" />
        </button>
      </div>
      <table role="grid" aria-label={`${label}, ${formatMonth(focus)}`} className="w-full border-collapse">
        <thead>
          <tr>
            {names.map((name) => (
              <th key={name} scope="col" abbr={name} className="pb-1 text-center text-[11px] font-medium text-ink-faint">
                {name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody onMouseLeave={() => setHover(null)}>
          {grid.map((week) => (
            <tr key={week[0]}>
              {week.map((day) => {
                const outside = day.slice(0, 7) !== focus.slice(0, 7);
                const off = disabled(day);
                const isToday = day === today;
                const single = typeof selected === "string" && selected === day;
                const edge = range !== null && (day === range.start || day === range.end);
                const inside = range !== null && day > range.start && day < range.end;
                const picked = single || edge || day === rangeAnchor;
                return (
                  <td key={day} role="gridcell" aria-selected={picked || inside || undefined} className="p-0 text-center">
                    <button
                      ref={(node) => {
                        if (node) cells.current.set(day, node);
                        else cells.current.delete(day);
                      }}
                      type="button"
                      tabIndex={day === focus ? 0 : -1}
                      aria-label={`${formatDateLong(day)}${isToday ? `, ${todayLabel}` : ""}`}
                      aria-current={isToday ? "date" : undefined}
                      aria-disabled={off || undefined}
                      onClick={() => {
                        if (off) return;
                        setFocus(day);
                        onSelect(day);
                      }}
                      onMouseEnter={() => setHover(day)}
                      onKeyDown={(event) => {
                        if ((event.key === "Enter" || event.key === " ") && off) event.preventDefault();
                        else onKeyDown(event, day);
                      }}
                      className={clsx(
                        "relative mx-auto grid h-9 w-full max-w-10 place-items-center rounded-md text-sm tabular-nums focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11",
                        picked
                          ? "bg-brand-strong font-semibold text-white"
                          : inside
                            ? "rounded-none bg-brand-soft text-ink"
                            : off
                              ? "cursor-not-allowed text-ink-faint/60 line-through decoration-ink-faint/40"
                              : outside
                                ? "text-ink-faint hover:bg-ink/[0.05]"
                                : "text-ink hover:bg-ink/[0.05]",
                        isToday && !picked && "font-semibold underline decoration-brand decoration-2 underline-offset-4",
                      )}
                    >
                      {Number(day.slice(8))}
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const TRIGGER = clsx(FIELD_FLUSH, "flex items-center gap-2 text-left disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-ink-faint");

export type DatePickerProps = {
  label: string;
  hideLabel?: boolean;
  hint?: string;
  error?: string | null;
  value: ISODate | null;
  onChange: (value: ISODate | null) => void;
  min?: ISODate;
  max?: ISODate;
  isDisabled?: (day: ISODate) => boolean;
  placeholder?: string;
  /** Offer a clear button (the date is optional). */
  clearable?: boolean;
  clearLabel?: string;
  disabled?: boolean;
  className?: string;
};

export function DatePicker({
  label,
  hideLabel,
  hint,
  error,
  value,
  onChange,
  min,
  max,
  isDisabled,
  placeholder = "Choose a date",
  clearable = false,
  clearLabel = "Clear the date",
  disabled = false,
  className,
}: DatePickerProps) {
  const [open, setOpen] = useState(false);
  return (
    <Field label={label} hideLabel={hideLabel} hint={hint} error={error} className={className}>
      {(control) => (
        <div className="relative mt-1 flex max-w-64 items-center gap-1">
          <Popover
            label={label}
            open={open}
            onOpenChange={setOpen}
            align="start"
            className="w-[min(20rem,calc(100vw-1rem))]"
            trigger={
              <button type="button" {...control} disabled={disabled} className={TRIGGER}>
                <CalendarDays aria-hidden className="h-4 w-4 shrink-0 text-ink-faint" />
                <span className={clsx("min-w-0 flex-1 truncate", !value && "text-ink-muted")}>
                  {value ? formatDateShort(value) : placeholder}
                </span>
              </button>
            }
          >
            <Calendar
              label={label}
              selected={value}
              min={min}
              max={max}
              isDisabled={isDisabled}
              focusOnMount
              onSelect={(day) => {
                onChange(day);
                setOpen(false);
              }}
            />
          </Popover>
          {clearable && value && !disabled ? (
            <button
              type="button"
              aria-label={clearLabel}
              onClick={() => onChange(null)}
              className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-ink-muted hover:bg-ink/[0.05] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11 touch:w-11"
            >
              <X aria-hidden className="h-4 w-4" />
            </button>
          ) : null}
        </div>
      )}
    </Field>
  );
}

export type DateRangePreset = { label: string; range: () => DateRange };

/** The everyday spans, all ending today in India. */
export function defaultRangePresets(): DateRangePreset[] {
  return [
    { label: "Today", range: () => ({ start: todayIST(), end: todayIST() }) },
    { label: "Yesterday", range: () => ({ start: addDays(todayIST(), -1), end: addDays(todayIST(), -1) }) },
    { label: "Last 7 days", range: () => ({ start: addDays(todayIST(), -6), end: todayIST() }) },
    { label: "Last 30 days", range: () => ({ start: addDays(todayIST(), -29), end: todayIST() }) },
    { label: "This month", range: () => ({ start: startOfMonth(todayIST()), end: todayIST() }) },
    {
      label: "Last month",
      range: () => {
        const start = addMonths(startOfMonth(todayIST()), -1);
        return { start, end: endOfMonth(start) };
      },
    },
  ];
}

export type DateRangePickerProps = {
  label: string;
  hideLabel?: boolean;
  hint?: string;
  error?: string | null;
  value: DateRange | null;
  onChange: (value: DateRange | null) => void;
  min?: ISODate;
  max?: ISODate;
  presets?: DateRangePreset[];
  presetsLabel?: string;
  placeholder?: string;
  /** Said while the second day is being chosen. */
  pickEndHint?: string;
  clearLabel?: string;
  disabled?: boolean;
  className?: string;
};

export function DateRangePicker({
  label,
  hideLabel,
  hint,
  error,
  value,
  onChange,
  min,
  max,
  presets = defaultRangePresets(),
  presetsLabel = "Quick ranges",
  placeholder = "Choose dates",
  pickEndHint = "Now choose the last day.",
  clearLabel = "Clear the dates",
  disabled = false,
  className,
}: DateRangePickerProps) {
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState<ISODate | null>(null);

  const choose = (day: ISODate) => {
    if (anchor === null) {
      setAnchor(day);
      return;
    }
    const [start, end] = compareDates(anchor, day) <= 0 ? [anchor, day] : [day, anchor];
    setAnchor(null);
    onChange({ start, end });
    setOpen(false);
  };

  return (
    <Field label={label} hideLabel={hideLabel} hint={hint} error={error} className={className}>
      {(control) => (
        <div className="relative mt-1 flex max-w-80 items-center gap-1">
          <Popover
            label={label}
            open={open}
            onOpenChange={(next) => {
              setOpen(next);
              if (!next) setAnchor(null);
            }}
            align="start"
            className="w-[min(32rem,calc(100vw-1rem))]"
            trigger={
              <button type="button" {...control} disabled={disabled} className={TRIGGER}>
                <CalendarDays aria-hidden className="h-4 w-4 shrink-0 text-ink-faint" />
                <span className={clsx("min-w-0 flex-1 truncate", !value && "text-ink-muted")}>
                  {value ? formatDateRange(value.start, value.end) : placeholder}
                </span>
              </button>
            }
          >
            <div className="flex flex-col gap-3 sm:flex-row">
              <div role="group" aria-label={presetsLabel} className="flex flex-wrap gap-1.5 sm:w-36 sm:flex-col sm:flex-nowrap">
                {presets.map((preset) => (
                  <button
                    key={preset.label}
                    type="button"
                    onClick={() => {
                      setAnchor(null);
                      onChange(preset.range());
                      setOpen(false);
                    }}
                    className="press rounded-md border border-line px-2.5 py-1.5 text-left text-meta font-medium text-ink hover:bg-ink/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11 sm:border-0"
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
              <div className="min-w-0 flex-1">
                <Calendar
                  label={label}
                  selected={anchor ? null : value}
                  rangeAnchor={anchor}
                  min={min}
                  max={max}
                  focusOnMount
                  onSelect={choose}
                />
                <p role="status" className="mt-2 min-h-5 text-meta text-ink-muted">
                  {anchor ? pickEndHint : ""}
                </p>
              </div>
            </div>
          </Popover>
          {value && !disabled ? (
            <button
              type="button"
              aria-label={clearLabel}
              onClick={() => onChange(null)}
              className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-ink-muted hover:bg-ink/[0.05] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11 touch:w-11"
            >
              <X aria-hidden className="h-4 w-4" />
            </button>
          ) : null}
        </div>
      )}
    </Field>
  );
}
