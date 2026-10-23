"use client";

import { useId } from "react";

import { DatePicker } from "@/components/arc/calendar";
import type { ISODate } from "@/components/arc/ist-dates";
import { FieldMessage } from "@/components/formValidation";
import { FIELD, FIELD_HINT, FIELD_LABEL } from "@/components/ui";

/**
 * A moment in IST, picked as a day (the kit `DatePicker`) and a time of day.
 *
 * The value is the `YYYY-MM-DDTHH:mm` an IST reader would type, the shape
 * `formatISTInput` produces and `istInputToInstant` turns into the instant the API stores,
 * so callers that used a `datetime-local` keep their draft shape. A native
 * `datetime-local` is not used because it renders in the browser's own locale with no
 * zone shown, and every time on this console is IST (D-709).
 *
 * A day with no time yet reads as `YYYY-MM-DDT` and converts to null, so a half-filled
 * field is never sent as midnight.
 */
export function IstDateTimeField({
  label,
  hint,
  error,
  value,
  onChange,
  min,
  clearable = false,
  disabled = false,
  defaultTime = "09:00",
  className,
}: {
  label: string;
  hint?: string;
  error?: string | null;
  value: string;
  onChange: (next: string) => void;
  min?: ISODate;
  clearable?: boolean;
  disabled?: boolean;
  /** The time filled in when a day is picked before any time is typed. */
  defaultTime?: string;
  className?: string;
}) {
  const uid = useId();
  const [day = "", time = ""] = value.split("T");
  const timeId = `${uid}-time`;
  const errorId = error ? `${uid}-error` : undefined;
  return (
    <fieldset className={className} aria-describedby={errorId}>
      <legend className={FIELD_LABEL}>{label} (IST)</legend>
      {hint ? <p className={`${FIELD_HINT} mt-0.5`}>{hint}</p> : null}
      <div className="flex flex-wrap items-end gap-3">
        <DatePicker
          label="Day"
          value={day || null}
          min={min}
          clearable={clearable}
          clearLabel={`Clear ${label.toLowerCase()}`}
          disabled={disabled}
          onChange={(next) => onChange(next ? `${next}T${time || defaultTime}` : "")}
          className="min-w-0 flex-1 basis-48"
        />
        <div className="w-32 shrink-0">
          <label htmlFor={timeId} className={FIELD_LABEL}>
            Time
          </label>
          <input
            id={timeId}
            type="time"
            value={time}
            disabled={disabled || !day}
            aria-invalid={error ? true : undefined}
            onChange={(event) => onChange(day ? `${day}T${event.target.value}` : "")}
            className={FIELD}
          />
        </div>
      </div>
      {error && errorId ? <FieldMessage id={errorId}>{error}</FieldMessage> : null}
    </fieldset>
  );
}
