"use client";

/**
 * THE slider: a value picked along a scale (a voice's speed, a pause before the agent
 * answers, hours of calls in the ROI calculator), and `RangeSlider` for a span along one.
 * Adapted from uiarc's `slider` (MIT, see ./LICENSE).
 *
 * Built on native `<input type="range">` rather than Arc's hand-rolled `role="slider"`:
 * the browser already gives the arrow, Page and Home/End keys, the value announcements and
 * the touch drag, and it works with no JavaScript. What this adds is the field around it
 * (label, the value as words, scale captions, tick marks), the filled part of the track,
 * and a thumb that is 24px under a coarse pointer — WCAG 2.2 SC 2.5.8's minimum for a
 * control a phone user drags.
 *
 * Give a precise number field beside it when an exact value matters (the ROI calculator
 * does): a thumb is for "about here", not for typing 437.
 */

import { useId, type CSSProperties, type InputHTMLAttributes, type ReactNode } from "react";
import clsx from "clsx";

import { FIELD_HINT, FIELD_LABEL } from "@/components/ui";

// The thumb, on both engines. The webkit thumb sits on the 6px track by a negative top
// margin of −(thumb − track) / 2: −5px for 16px, −9px for 24px; Firefox centres its own.
const THUMB =
  "[&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-surface [&::-moz-range-thumb]:bg-brand-strong [&::-moz-range-thumb]:shadow-raised [&::-webkit-slider-thumb]:-mt-[5px] [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-surface [&::-webkit-slider-thumb]:bg-brand-strong [&::-webkit-slider-thumb]:shadow-raised touch:[&::-moz-range-thumb]:h-6 touch:[&::-moz-range-thumb]:w-6 touch:[&::-webkit-slider-thumb]:-mt-[9px] touch:[&::-webkit-slider-thumb]:h-6 touch:[&::-webkit-slider-thumb]:w-6 focus-visible:outline-none focus-visible:[&::-moz-range-thumb]:ring-2 focus-visible:[&::-moz-range-thumb]:ring-brand focus-visible:[&::-moz-range-thumb]:ring-offset-2 focus-visible:[&::-webkit-slider-thumb]:ring-2 focus-visible:[&::-webkit-slider-thumb]:ring-brand focus-visible:[&::-webkit-slider-thumb]:ring-offset-2 disabled:cursor-not-allowed disabled:[&::-webkit-slider-thumb]:bg-ink-faint disabled:[&::-moz-range-thumb]:bg-ink-faint";

// The track draws its own fill from `--fill` (0–100%), so the chosen part reads at a glance.
const TRACK =
  "[&::-webkit-slider-runnable-track]:h-1.5 [&::-webkit-slider-runnable-track]:rounded-full [&::-webkit-slider-runnable-track]:bg-[linear-gradient(to_right,var(--brand-strong)_var(--fill,0%),var(--line)_var(--fill,0%))] [&::-moz-range-track]:h-1.5 [&::-moz-range-track]:rounded-full [&::-moz-range-track]:bg-line [&::-moz-range-progress]:h-1.5 [&::-moz-range-progress]:rounded-full [&::-moz-range-progress]:bg-brand-strong";

const INPUT = "block w-full cursor-pointer appearance-none bg-transparent touch:min-h-11";

function percent(value: number, min: number, max: number): number {
  return max === min ? 0 : ((value - min) / (max - min)) * 100;
}

function Ticks({ marks, min, max }: { marks: number[]; min: number; max: number }) {
  return (
    <div aria-hidden className="relative mx-2 h-1.5">
      {marks.map((mark) => (
        <span
          key={mark}
          className="absolute top-0 h-1.5 w-px bg-ink-faint/50"
          style={{ left: `${percent(mark, min, max)}%` }}
        />
      ))}
    </div>
  );
}

/**
 * The bare track, for a composite control that draws its own label and value (the ROI
 * calculator pairs it with a number field). Give it an `aria-label` or an `id` a label
 * points at. Everything else should use `Slider`.
 */
export function SliderTrack({
  value,
  min,
  max,
  onValueChange,
  className,
  style,
  ...rest
}: Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "value" | "min" | "max" | "onChange"> & {
  value: number;
  min: number;
  max: number;
  onValueChange: (value: number) => void;
}) {
  const held = Math.min(max, Math.max(min, value));
  return (
    <input
      {...rest}
      type="range"
      min={min}
      max={max}
      value={held}
      onChange={(event) => onValueChange(Number(event.target.value))}
      style={{ ...style, "--fill": `${percent(held, min, max)}%` } as CSSProperties}
      className={clsx(INPUT, TRACK, THUMB, className)}
    />
  );
}

export type SliderProps = {
  label: string;
  hideLabel?: boolean;
  hint?: ReactNode;
  value: number;
  onChange: (value: number) => void;
  min: number;
  max: number;
  step?: number;
  /** The value in words, shown beside the label and spoken: "1.2 times normal", "700 ms". */
  valueText?: (value: number) => string;
  /** What a screen reader hears, when the shown text is a symbol ("1.20×" → "1.20 times normal"). */
  spokenText?: (value: number) => string;
  /** Captions under the track, spread from end to end: ["Slower", "Normal", "Faster"]. */
  scale?: ReactNode[];
  /** Values to mark on the track (presets). */
  marks?: number[];
  /** A small control on the label row, such as "Reset". */
  labelAction?: ReactNode;
  disabled?: boolean;
  id?: string;
  className?: string;
};

export function Slider({
  label,
  hideLabel = false,
  hint,
  value,
  onChange,
  min,
  max,
  step = 1,
  valueText = (v) => String(v),
  spokenText,
  scale,
  marks,
  labelAction,
  disabled = false,
  id,
  className,
}: SliderProps) {
  const generated = useId();
  const inputId = id ?? generated;
  const scaleId = scale ? `${inputId}-scale` : undefined;
  const hintId = hint ? `${inputId}-hint` : undefined;
  const held = Math.min(max, Math.max(min, value));
  const text = valueText(held);
  return (
    <div className={clsx("min-w-0", className)}>
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={inputId} className={hideLabel ? "sr-only" : FIELD_LABEL}>
          {label}
        </label>
        <span className="flex items-baseline gap-2">
          <span aria-hidden className="text-meta tabular-nums text-ink">
            {text}
          </span>
          {labelAction}
        </span>
      </div>
      {hint ? (
        <span id={hintId} className={FIELD_HINT}>
          {hint}
        </span>
      ) : null}
      <SliderTrack
        id={inputId}
        min={min}
        max={max}
        step={step}
        value={held}
        disabled={disabled}
        onValueChange={onChange}
        aria-valuetext={spokenText ? spokenText(held) : text}
        aria-describedby={[hintId, scaleId].filter(Boolean).join(" ") || undefined}
        className="mt-2"
      />
      {marks ? <Ticks marks={marks} min={min} max={max} /> : null}
      {scale ? (
        <div id={scaleId} className={clsx(FIELD_HINT, "flex justify-between gap-2")}>
          {scale.map((caption, index) => (
            <span key={index}>{caption}</span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export type RangeSliderProps = Omit<SliderProps, "value" | "onChange" | "labelAction" | "marks"> & {
  value: [number, number];
  onChange: (value: [number, number]) => void;
  /** Names of the two thumbs, for a screen reader. */
  lowerLabel?: string;
  upperLabel?: string;
};

/**
 * Two native range inputs over one drawn track. Each input ignores the pointer except on
 * its own thumb, so either end can be grabbed; neither thumb can pass the other.
 */
export function RangeSlider({
  label,
  hideLabel = false,
  hint,
  value,
  onChange,
  min,
  max,
  step = 1,
  valueText = (v) => String(v),
  scale,
  lowerLabel = "From",
  upperLabel = "To",
  disabled = false,
  id,
  className,
}: RangeSliderProps) {
  const generated = useId();
  const baseId = id ?? generated;
  const [low, high] = value;
  const lo = Math.max(min, Math.min(low, high));
  const hi = Math.min(max, Math.max(low, high));
  const thumbOnly =
    "pointer-events-none absolute inset-x-0 top-1/2 -translate-y-1/2 [&::-webkit-slider-runnable-track]:h-1.5 [&::-webkit-slider-runnable-track]:bg-transparent [&::-moz-range-track]:bg-transparent [&::-webkit-slider-thumb]:pointer-events-auto [&::-moz-range-thumb]:pointer-events-auto";
  return (
    <div role="group" aria-labelledby={`${baseId}-label`} className={clsx("min-w-0", className)}>
      <div className="flex items-baseline justify-between gap-3">
        <span id={`${baseId}-label`} className={hideLabel ? "sr-only" : FIELD_LABEL}>
          {label}
        </span>
        <span aria-hidden className="text-meta tabular-nums text-ink">
          {valueText(lo)} – {valueText(hi)}
        </span>
      </div>
      {hint ? <span className={FIELD_HINT}>{hint}</span> : null}
      <div className="relative mt-2 h-6 touch:h-11">
        <div aria-hidden className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-line" />
        <div
          aria-hidden
          className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-brand-strong"
          style={{ left: `${percent(lo, min, max)}%`, right: `${100 - percent(hi, min, max)}%` }}
        />
        <input
          type="range"
          aria-label={`${label}: ${lowerLabel}`}
          min={min}
          max={max}
          step={step}
          value={lo}
          disabled={disabled}
          aria-valuetext={valueText(lo)}
          onChange={(event) => onChange([Math.min(Number(event.target.value), hi), hi])}
          className={clsx(INPUT, thumbOnly, THUMB)}
        />
        <input
          type="range"
          aria-label={`${label}: ${upperLabel}`}
          min={min}
          max={max}
          step={step}
          value={hi}
          disabled={disabled}
          aria-valuetext={valueText(hi)}
          onChange={(event) => onChange([lo, Math.max(Number(event.target.value), lo)])}
          className={clsx(INPUT, thumbOnly, THUMB)}
        />
      </div>
      {scale ? (
        <div className={clsx(FIELD_HINT, "flex justify-between gap-2")}>
          {scale.map((caption, index) => (
            <span key={index}>{caption}</span>
          ))}
        </div>
      ) : null}
    </div>
  );
}
