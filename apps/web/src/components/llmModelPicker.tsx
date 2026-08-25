"use client";

/**
 * THE MODEL PICKER — one list of choices with what each ADDS to the bill against it, used
 * by both screens that can change a model.
 *
 * The organisation default (`/c/[slug]/settings/models`) and the per-agent override
 * (`/c/[slug]/agents/[agentId]`) ask the same question of the same catalogue and differ
 * only in what the first option MEANS — "use Calevate's default" on one, "use my
 * organisation's default" on the other. Two pickers would have been two places for the
 * price to stop being shown, and the price is the entire reason this control exists.
 *
 * ## Why the price is on the row and not in a help link
 *
 * `client_surcharge_inr_per_minute` is what choosing that model ADDS to this account's
 * bill for every minute it runs (D-455) — the plan's own `llm_model_surcharge`, and `0`
 * on the model their rate is struck at. A client changing model is changing what every
 * call costs them, and a picker that hides that is a trap: the choice looks like a
 * quality setting and behaves like a price list. So each row carries the surcharge as the
 * server's own digits, plus how it compares with what is in force — the comparison
 * because a column of rupee figures is a table a reader has to do arithmetic on, and the
 * arithmetic is where they get it wrong.
 *
 * **THE FIGURE HERE IS THE CLIENT'S, NOT OURS, AND THAT IS A CORRECTION.** This control
 * used to render `platform_cost_inr_per_minute` — what the language leg costs CALEVATE at
 * list price — under the words "what every call costs them". It was wrong twice over
 * (`apps/api/billing/rates.py::llm_cost_inr_per_minute` states both halves): it printed a
 * number nobody is charged, and it published our supplier cost, and therefore our margin,
 * to the account it is a margin on. That figure now stays on the admin console, labelled
 * as ours; this control shows what the client will actually pay.
 *
 * A surcharge of zero — every plan until a founder sets one — reads "no extra charge",
 * not "₹0.00", because the honest client-facing sentence is that the choice costs them
 * nothing rather than that it costs them a rupee amount of nothing.
 *
 * The comparison is EXACT (`lib/llmRates.ts`) and refuses rather than rounds: no figure
 * on this control is ever produced by parsing a decimal into a float (hard rule 7).
 *
 * ## A row the server would refuse is never offered
 *
 * `ModelChoice.unavailable` carries the reason a model cannot be chosen here, and such a
 * row renders SHOWN AND DISABLED with that reason beside it. It is a property of the
 * control rather than of each screen on purpose: the admin console already got this right
 * by hand while both client screens mapped the catalogue straight into selectable rows,
 * so a client could pick a model with no Azure deployment behind it, see its price, and
 * be answered with `llm_model_not_deployed`. One control, one rendering, and the client
 * screens cannot be the pair that forgets.
 *
 * ## The markup, and why it is a radio group rather than a `<select>`
 *
 * A `<select>` can hold model names and cannot hold prices — the option text would have to
 * become "gpt-4.1-mini — +₹1.50/min, ₹1.50 more a minute", which is a sentence no screen
 * reader user wants read at them to compare two. Real `<input type="radio">`s inside their
 * labels, visually hidden rather than replaced: arrow keys move between them, the group
 * announces itself from its `<legend>`, each option's accessible name is the whole row
 * INCLUDING its price, and what is painted is drawn from the input's own `checked` state so
 * the two cannot disagree. Same shape as `agents/DirectionChoice.tsx`, which is what keeps
 * this from being a second visual idiom.
 *
 * ## Grouped by provider, so three vendors read as three vendors (D-456)
 *
 * The catalogue is no longer one vendor's models: a client chooses between Azure OpenAI,
 * OpenAI and Google Gemini. The rows that belong to a provider gather under that provider's
 * name — a labelled sub-group (`role="group"` + `aria-labelledby`) inside the one radio
 * group, so a screen reader announces the vendor on entering it and the provider need not
 * be crammed into every row's accessible name. The inherit row and any retired model belong
 * to no provider and render first, ungrouped. It is ONE radio group throughout: the choice
 * is one model among all of them, so arrow keys cross the group boundaries and only the
 * grouping — the reading of the same choice — changes. Providers appear in the order the
 * server sent them, presented on equal footing: no vendor is the header act.
 */

import { CheckCircle2 } from "lucide-react";

import { formatRupeeRate } from "@/components/ui";
import { providerLabel } from "@/lib/api/llmModels";
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
  /**
   * The second line — the model-specific note, or what inheriting resolves to. NO LONGER
   * the provider: that is the group heading now (see `provider`), so a model row that has
   * nothing else to say carries an empty string and the line is not painted at all. The
   * inherit row and a retired model still fill it, because for them it is the only place
   * that says what the row means.
   */
  detail: string;
  /**
   * THE PROVIDER THIS MODEL RUNS ON, as the server's own key (`azure_openai`, `openai`,
   * `google`), or absent for the rows that belong to no provider — the inherit row, and a
   * retired model the catalogue can no longer place. Rows carrying one are GROUPED under a
   * `providerLabel` heading and presented on equal footing (D-456); rows without one render
   * first, ungrouped. Passed as the raw key rather than the label so grouping is stable and
   * the one spelling of each provider's name lives in `providerLabel`.
   */
  provider?: string | null;
  /**
   * WHAT CHOOSING THIS ROW ADDS TO THE CLIENT'S BILL, per minute, as the server's digits.
   *
   * `"0"` is a real answer and means "no extra charge" — the state every plan is in until
   * a founder sets `plans.llm_model_surcharge`. `null` is "we cannot say", which is a
   * different thing and renders as `—`: a model withdrawn from the catalogue, or a build
   * whose API does not carry the field.
   *
   * NOT our cost to run the model. That figure exists (`platform_cost_inr_per_minute`)
   * and belongs on the operator's console; see the module docstring for why it may not
   * appear on a client's screen.
   */
  surcharge: string | null;
  /** A short badge: "Calevate's default", "your organisation default". */
  badge?: string;
  /**
   * Is this the model in force right now — the one every other row is compared against?
   *
   * It gets "the model running now" instead of a comparison, because "same price" is what a
   * row would otherwise say about itself, and a reader who sees it on two rows cannot
   * tell which of the two they are on.
   */
  baseline?: boolean;
  /**
   * WHY THIS ROW CANNOT BE PICKED, or `null`/absent when it can — the server's own
   * sentence, printed beside a row that is SHOWN AND DISABLED rather than hidden.
   *
   * `is_available: false` means the platform cannot put that model on the wire, so
   * `PUT`/`PATCH` refuse it with `llm_model_not_deployed`: a selection we accepted but could
   * not address would quote the client one model's price for calls another model answered. A
   * picker that offered such a row would hand the person a 422 for a decision the screen had
   * already shown them the price of.
   *
   * THE SENTENCE IS AUDIENCE-APPROPRIATE AND THE SERVER CHOOSES IT BY REALM. This control is
   * realm-agnostic — it prints whatever the caller passes. The client screens feed it the
   * server's CLIENT reason ("ask your Calevate team to enable it"); the admin console feeds
   * the OPERATOR ground (a key, a deployment, a price). Same rendering either way, because
   * the fork lives in the API (`agents/llm_models.py::unofferable_reason`, keyed on the
   * realm's `audience`) — not here and not duplicated per screen.
   *
   * Shown-and-disabled rather than filtered out: a missing row tells a reader nothing, and a
   * row that says why tells them the one thing they can act on.
   */
  unavailable?: string | null;
}

/**
 * How this option's price compares with the one in force, as a sentence or as nothing.
 *
 * Nothing — not "same price" — whenever either side is missing or unparseable. Two models
 * costing the same is a claim, and a screen that makes it from an absent figure is the
 * §52 defect applied to money.
 */
function priceComparison(surcharge: string | null, baseline: string | null): string | null {
  const order = compareRates(surcharge, baseline);
  if (order === "unknown") return null;
  // Two rows that both cost nothing extra need no comparison: the row already says "No
  // extra charge", and "same price" under it is a second way of saying nothing happened.
  if (order === "same") return compareRates(surcharge, "0") === "same" ? null : "same price";
  const difference = rateDifference(surcharge, baseline);
  if (difference === null) return null;
  return `${formatRupeeRate(difference)} ${order === "dearer" ? "more" : "less"} a minute`;
}

/**
 * The row's own money line: the surcharge, or the words for not having one.
 *
 * "No extra charge" rather than "₹0.00 / min" for a zero, because a client asking what a
 * model costs them is asking a yes/no question first and a rupee question second — and a
 * column of "₹0.00 / min" on every row reads as a price list nobody has filled in. `—`
 * stays for `null`, which is the different claim that we cannot say (see `surcharge`).
 */
function surchargeLabel(surcharge: string | null): string {
  if (surcharge === null) return "—";
  return compareRates(surcharge, "0") === "same"
    ? "No extra charge"
    : `+${formatRupeeRate(surcharge)} / min`;
}

export function ModelPicker({
  name,
  legend,
  hint,
  choices,
  value,
  baselineSurcharge,
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
   * The surcharge everything is compared against — the one the model in force RIGHT NOW
   * carries, not the row the user has selected. Comparing against the selection would
   * make the differences move as the user clicked around, which is the one thing a price
   * column must not do.
   */
  baselineSurcharge: string | null;
  disabled?: boolean;
  onChange: (next: string | null) => void;
}) {
  const row = (choice: ModelChoice) => {
    const checked = choice.value === value;
    const comparison = choice.baseline
      ? null
      : priceComparison(choice.surcharge, baselineSurcharge);
    // `!= null` covers both `null` and an absent property, and nothing else: an
    // empty string would be a reason the server sent and is not a state to swallow.
    const blocked = choice.unavailable != null;
    return (
      <label
        key={choice.value ?? "__inherit__"}
        /*
         * `has-[:focus-visible]` — WCAG 2.4.7 Focus Visible (AA), and the failure this
         * fixes is technique F78 verbatim: the `<input type="radio">` below is `sr-only`,
         * which removes the browser's own focus ring, and the label styled only `checked`
         * and `hover`. So a keyboard user tabbing into this group saw NOTHING move. On a
         * native radio group arrowing moves the selection too, which hides the defect —
         * until the group is disabled, or the user tabs in without arrowing, and then
         * there is no indicator at all. On the control that picks which model the client
         * pays for.
         *
         * `focus-visible` rather than `focus`, so a mouse click on a row does not leave a
         * ring behind it. The ring is `ring-brand` on `ring-offset-app` — the same
         * treatment `components/actionButton.tsx` already uses — so the two focus styles
         * in this console are one style. axe cannot evaluate a focus indicator and jsdom
         * has no layout, so `tests/contrast.test.ts` guards this at the source instead.
         */
        className={`flex flex-wrap items-start justify-between gap-3 rounded-card border p-3 transition-colors has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-strong has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-app ${
          checked ? "border-brand bg-brand-soft" : "border-line bg-surface"
        } ${
          disabled || blocked
            ? "cursor-not-allowed opacity-60"
            : "cursor-pointer hover:bg-black/5 dark:hover:bg-white/5"
        }`}
      >
        <input
          type="radio"
          name={name}
          className="sr-only"
          checked={checked}
          disabled={disabled || blocked}
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
          {/* The model-specific note, only when there IS one: a plain model row's provider
              now lives in the group heading above it, so its second line is empty and is
              not painted. */}
          {choice.detail && (
            <span className="mt-0.5 block pl-6 text-xs text-ink-faint">{choice.detail}</span>
          )}
          {/* The server's own words for why the row is dead, in the row. Amber
              rather than muted: it is the difference between "this costs more" and
              "this cannot be chosen at all", and a reader skimming prices must not
              have to work out which rows are real. */}
          {blocked && (
            <span className="mt-0.5 block pl-6 text-xs font-medium text-amber-700 dark:text-amber-400">
              Cannot be chosen — {choice.unavailable}
            </span>
          )}
        </span>
        {/* WHAT THIS ROW ADDS TO THEIR BILL, as the server's own digits. `—` where
            we cannot say: a model withdrawn from the catalogue, or a build whose
            API does not carry the field. An absent figure is said as absent, never
            as free — "No extra charge" is reserved for a surcharge we HAVE and
            which is zero. */}
        <span className="shrink-0 text-right">
          <span className="block text-sm font-semibold tabular-nums text-ink">
            {surchargeLabel(choice.surcharge)}
          </span>
          {(choice.baseline || comparison !== null) && (
            <span className="mt-0.5 block text-xs text-ink-faint">
              {choice.baseline ? "the model running now" : comparison}
            </span>
          )}
        </span>
      </label>
    );
  };

  // Rows with no provider — the inherit row, and a retired model the catalogue can no
  // longer place — render first and ungrouped. The rest gather under their provider's name,
  // keyed by the server's raw provider value and in first-appearance order, so the server's
  // ordering and the special rows' position ahead of the catalogue both survive grouping.
  const ungrouped = choices.filter((choice) => choice.provider == null);
  const groups: { key: string; label: string; rows: ModelChoice[] }[] = [];
  for (const choice of choices) {
    if (choice.provider == null) continue;
    const group = groups.find((candidate) => candidate.key === choice.provider);
    if (group) group.rows.push(choice);
    else groups.push({ key: choice.provider, label: providerLabel(choice.provider), rows: [choice] });
  }

  return (
    <fieldset>
      <legend className="text-xs font-medium text-ink-muted">{legend}</legend>
      {hint && <p className="mt-1 text-xs text-ink-faint">{hint}</p>}
      {ungrouped.length > 0 && <div className="mt-2 space-y-2">{ungrouped.map(row)}</div>}
      {groups.map((group, index) => {
        // Index rather than the provider key in the id: the key is the server's raw value
        // and an id built from it would carry whatever punctuation the server chose. The
        // heading LABELS the sub-group so a screen reader names the vendor on entering it.
        const headingId = `${name}-provider-${index}`;
        return (
          <div key={group.key} role="group" aria-labelledby={headingId} className="mt-4">
            <p
              id={headingId}
              className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint"
            >
              {group.label}
            </p>
            <div className="mt-2 space-y-2">{group.rows.map(row)}</div>
          </div>
        );
      })}
    </fieldset>
  );
}
