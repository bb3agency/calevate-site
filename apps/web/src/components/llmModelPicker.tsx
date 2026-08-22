"use client";

/**
 * THE MODEL PICKER — one list of choices with a price against each, used by both screens
 * that can change a model.
 *
 * The organisation default (`/c/[slug]/settings/models`) and the per-agent override
 * (`/c/[slug]/agents/[agentId]`) ask the same question of the same catalogue and differ
 * only in what the first option MEANS — "use Calevate's default" on one, "use my
 * organisation's default" on the other. Two pickers would have been two places for the
 * price to stop being shown, and the price is the entire reason this control exists.
 *
 * ## Why the price is on the row and not in a help link
 *
 * `inr_per_minute_five_min` is what a minute of a five-minute call costs on that model. A
 * client changing model is changing what every call costs them, and a picker that hides
 * that is a trap: the choice looks like a quality setting and behaves like a price list.
 * So each row carries the rate as the server's own digits, plus how it compares with what
 * is in force — the comparison because a column of four rupee figures is a table a reader
 * has to do arithmetic on, and the arithmetic is where they get it wrong.
 *
 * The comparison is EXACT (`lib/llmRates.ts`) and refuses rather than rounds: no figure
 * on this control is ever produced by parsing a decimal into a float (hard rule 7).
 *
 * ## The markup, and why it is a radio group rather than a `<select>`
 *
 * A `<select>` can hold four model names and cannot hold four prices — the option text
 * would have to become "gpt-4o-mini — ₹0.24/min, ₹0.06 more a minute", which is a
 * sentence no screen reader user wants read at them four times to compare two. Real
 * `<input type="radio">`s inside their labels, visually hidden rather than replaced:
 * arrow keys move between them, the group announces itself from its `<legend>`, each
 * option's accessible name is the whole row INCLUDING its price, and what is painted is
 * drawn from the input's own `checked` state so the two cannot disagree. Same shape as
 * `agents/DirectionChoice.tsx`, which is what keeps this from being a second visual idiom.
 */

import { CheckCircle2 } from "lucide-react";

import { formatRupeeRate } from "@/components/ui";
import { compareRates, rateDifference } from "@/lib/llmRates";

/** One row of the picker. */
export interface ModelChoice {
  /**
   * What `onChange` reports and what the API is sent — `null` is the INHERIT row.
   *
   * `null` is a value here, not an absence: on the organisation screen it means "use
   * whatever Calevate runs by default, including after we change it", and on the agent
   * screen it means "follow my organisation". Both are real choices a client makes.
   */
  value: string | null;
  label: string;
  /** The second line — the provider, or what inheriting resolves to. */
  detail: string;
  /** The per-minute price as the server's digits, or `null` when we cannot say. */
  rate: string | null;
  /** A short badge: "Calevate's default", "your organisation default". */
  badge?: string;
  /**
   * Is this the model in force right now — the one every other row is priced against?
   *
   * It gets "what you pay now" instead of a comparison, because "same price" is what a
   * row would otherwise say about itself, and a reader who sees it on two rows cannot
   * tell which of the two they are on.
   */
  baseline?: boolean;
}

/**
 * How this option's price compares with the one in force, as a sentence or as nothing.
 *
 * Nothing — not "same price" — whenever either side is missing or unparseable. Two models
 * costing the same is a claim, and a screen that makes it from an absent figure is the
 * §52 defect applied to money.
 */
function priceComparison(rate: string | null, baseline: string | null): string | null {
  const order = compareRates(rate, baseline);
  if (order === "unknown") return null;
  if (order === "same") return "same price";
  const difference = rateDifference(rate, baseline);
  if (difference === null) return null;
  return `${formatRupeeRate(difference)} ${order === "dearer" ? "more" : "less"} a minute`;
}

export function ModelPicker({
  name,
  legend,
  hint,
  choices,
  value,
  baselineRate,
  disabled,
  onChange,
}: {
  /** Scopes the radio group, so an agent screen and a settings screen never share one. */
  name: string;
  legend: string;
  hint?: string;
  choices: ModelChoice[];
  value: string | null;
  /**
   * The rate everything is compared against — the price of the model in force RIGHT NOW,
   * not of the row the user has selected. Comparing against the selection would make the
   * differences move as the user clicked around, which is the one thing a price column
   * must not do.
   */
  baselineRate: string | null;
  disabled?: boolean;
  onChange: (next: string | null) => void;
}) {
  return (
    <fieldset>
      <legend className="text-xs font-medium text-ink-muted">{legend}</legend>
      {hint && <p className="mt-1 text-xs text-ink-faint">{hint}</p>}
      <div className="mt-2 space-y-2">
        {choices.map((choice) => {
          const checked = choice.value === value;
          const comparison = choice.baseline ? null : priceComparison(choice.rate, baselineRate);
          return (
            <label
              key={choice.value ?? "__inherit__"}
              className={`flex cursor-pointer flex-wrap items-start justify-between gap-3 rounded-card border p-3 transition-colors ${
                checked
                  ? "border-brand bg-brand-soft"
                  : "border-line bg-surface hover:bg-black/5 dark:hover:bg-white/5"
              } ${disabled ? "cursor-not-allowed opacity-60" : ""}`}
            >
              <input
                type="radio"
                name={name}
                className="sr-only"
                checked={checked}
                disabled={disabled}
                onChange={() => onChange(choice.value)}
              />
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  {checked ? (
                    <CheckCircle2 aria-hidden className="h-4 w-4 shrink-0 text-brand" />
                  ) : (
                    <span aria-hidden className="h-4 w-4 shrink-0 rounded-full border border-line" />
                  )}
                  <span className="text-sm font-semibold text-ink">{choice.label}</span>
                  {choice.badge && (
                    <span className="rounded-full border border-line px-2 py-0.5 text-[11px] font-medium text-ink-muted">
                      {choice.badge}
                    </span>
                  )}
                </span>
                <span className="mt-0.5 block pl-6 text-xs text-ink-faint">{choice.detail}</span>
              </span>
              {/* The price, as the server's own digits. `—` where there is none: a model
                  withdrawn from the catalogue, or a build whose API does not price it. An
                  absent rate is said as absent, never as free. */}
              <span className="shrink-0 text-right">
                <span className="block text-sm font-semibold tabular-nums text-ink">
                  {choice.rate === null ? "—" : `${formatRupeeRate(choice.rate)} / min`}
                </span>
                {(choice.baseline || comparison !== null) && (
                  <span className="mt-0.5 block text-xs text-ink-faint">
                    {choice.baseline ? "what you pay now" : comparison}
                  </span>
                )}
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
