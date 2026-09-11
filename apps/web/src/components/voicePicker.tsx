"use client";

/**
 * THE VOICE PICKER — every catalogue voice, grouped by the tier a client reads, with the
 * refusal on the ones that cannot be chosen and the per-minute rate on the tier itself.
 *
 * ## Why this is not a `<select>` any more
 *
 * It was one, and a `<select>` cannot hold this. D-547 made the catalogue TWO TIERS at two
 * different per-minute rates, and an `<option>` can carry neither a price nor the sentence
 * saying why a row is dead — they would have to be crammed into the option text, which is
 * what a screen reader then reads out in full when comparing two voices. So this is the
 * same control `components/llmModelPicker.tsx` already is, for the same reasons and in the
 * same markup: real `<input type="radio">`s inside their labels, `sr-only` rather than
 * replaced, one radio group throughout with labelled sub-groups (`role="group"` +
 * `aria-labelledby`) so arrow keys cross the tier boundary and only the READING changes.
 * Two visual idioms for "pick one priced thing from a grouped list" would be one too many.
 *
 * ## Never a shorter list — the whole reason `offerable_voices()` has the shape it has
 *
 * A voice that cannot be offered here is rendered SHOWN, REACHABLE AND UNSELECTABLE
 * (`aria-disabled` plus the `onChange` guard, never a native `disabled` — a disabled input
 * is skipped by the keyboard and by a screen reader, which would hide the refusal from
 * exactly the readers who cannot see it beside the row) with the server's own sentence
 * beside it (`apps/api/agents/voice_offer.py`: three grounds, three sentences,
 * each naming the one action that fixes it). Filtering the row out instead is the defect
 * that module was built to prevent: an absent Studio row is indistinguishable from a
 * product that does not sell a Studio voice, so the operator who pasted the key an hour ago
 * has no way to see that the PRICE is what is still missing. The sentence is printed
 * VERBATIM — this control never composes its own from the flags and gets the tone wrong.
 *
 * ## The tier's name comes from the server; the vendor's name is never rendered
 *
 * Grouping is by `tier_label` ("Clear", "Studio"), which is the API's word for the tier
 * (`apps/api/billing/rates.py::VOICE_TIER_LABELS`, one definition, in Python). It is NOT by
 * `provider`: `sarvam`/`cartesia` name the VENDOR, they key the money and the metering, and
 * no human-facing surface says them (founder, 7 Sep 2026). A voice arriving with no label —
 * an API build that does not send the field yet — renders UNGROUPED rather than under a
 * vendor name, because a tier is either named by the server or not named at all.
 *
 * ## The rate is a property of the tier, and of THIS account, at THIS moment
 *
 * It sits on the group heading rather than on every row, because that is what it is a fact
 * about: under D-547 a minute costs the rate frozen on the credit lot it draws from, spent
 * oldest-first, so two voices in one tier cost the same and the figure is not the product's
 * — it is this account's oldest open lot's. When it is absent, NOTHING is printed. Not a
 * dash, not a "from" price, not last month's rate: the picker's job here is to avoid
 * quoting a price nobody is charged (hard rule 7).
 */

import { CheckCircle2 } from "lucide-react";

import { formatRupeeRate } from "@/components/ui";
import { voiceTierRate, type OfferedVoice, type VoiceTierRates } from "@/lib/api/voices";

/** One tier heading's money line, or `null` when there is no rate to state. */
export function tierRateReading(
  rates: VoiceTierRates | undefined,
  provider: string | null | undefined,
): { rate: string; note: string } | null {
  const tier = voiceTierRate(rates, provider);
  if (!tier || tier.inr_per_min === null) return null;
  return {
    rate: `${formatRupeeRate(tier.inr_per_min)} / min`,
    // WHY the figure can move: credit is spent oldest purchase first and each purchase
    // carries its own rates, so this is the price of the NEXT minute and not a permanent
    // one. Saying how many purchases sit behind it is honest without pretending to know
    // when the balance crosses over — that depends on calls nobody has made yet.
    note:
      tier.further_open_lots === 0
        ? "the rate on this account's credit"
        : `the rate on this account's oldest credit — ${tier.further_open_lots} later purchase${
            tier.further_open_lots === 1 ? "" : "s"
          } behind it at their own rates`,
  };
}

/**
 * The tier's name, or null. Never the vendor's — see the module docstring.
 *
 * **THE WIRE NOW REQUIRES `tier_label`** (`OfferedVoiceOut`, generated), so a well-behaved
 * server always sends one and the null arm is unreachable through it. The check is KEPT
 * anyway, and deliberately: it is two comparisons against a server regression, and the
 * only fallback available if it were removed is `voice.provider` — the VENDOR's name,
 * which is the one name a client-facing surface may not print (founder, 7 Sep 2026). A
 * voice with no heading still lists; a voice headed "cartesia" would be a rename nobody
 * approved.
 */
function tierLabel(voice: OfferedVoice): string | null {
  const label = voice.tier_label;
  return typeof label === "string" && label !== "" ? label : null;
}

export function VoicePicker({
  name,
  legend,
  hint,
  voices,
  value,
  rates,
  disabled,
  onChange,
}: {
  /** Scopes the radio group, so two pickers on one screen never share a selection. */
  name: string;
  legend: string;
  hint?: string;
  voices: readonly OfferedVoice[];
  /** The id currently chosen — `""` for an agent with no voice set. */
  value: string;
  /** This account's per-tier rates. Absent means no price is printed anywhere. */
  rates?: VoiceTierRates;
  disabled?: boolean;
  onChange: (voiceId: string) => void;
}) {
  const row = (voice: OfferedVoice) => {
    const checked = voice.id === value;
    // `!= null` covers a null and an absent property and nothing else: an empty string
    // would be a sentence the server sent, and swallowing it would hide a refusal.
    const blocked = voice.unavailable_reason != null || !voice.offerable;
    // The refusal's own id, so the input can point at it — see `aria-describedby` below.
    // Built from `name` as well as the voice id, because two pickers on one screen would
    // otherwise mint the same id twice and both inputs would describe the first one.
    const reasonId = `${name}-${voice.id}-reason`;
    return (
      <label
        key={voice.id}
        /* `has-[:focus-visible]` for `llmModelPicker`'s reason, verbatim: the input below is
           `sr-only`, so without this a keyboard user tabbing in sees nothing move (WCAG
           2.4.7, technique F78). Same ring as `components/actionButton.tsx`, so this console
           has one focus style rather than two. */
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
          value={voice.id}
          className="sr-only"
          checked={checked}
          /* THE WHOLE PICKER'S `disabled` IS A REAL `disabled`; A BLOCKED ROW'S IS NOT, and
             the difference is the point. A `disabled` input is removed from the tab order
             and skipped by a screen reader's arrow keys, so a keyboard or screen-reader user
             could never land on a refused voice — and the refusal sentence beside it is the
             ENTIRE reason that row is rendered rather than filtered out (see the module
             docstring). `aria-disabled` keeps the row reachable and announces it as
             unavailable; the `onChange` guard below is what actually keeps it unselectable,
             which is why this is a swap of the mechanism and not a relaxation of the rule.
             A picker disabled as a whole is a different case — there is nothing to read on
             any row — so it stays natively disabled. */
          disabled={disabled}
          aria-disabled={blocked || undefined}
          /* WHY it is refused, spoken. The sentence is rendered below for a sighted reader;
             without this it is orphaned from the control for everyone else, who would hear
             "unavailable" and no reason. */
          aria-describedby={blocked ? reasonId : undefined}
          /* `disabled` used to be the control and this guard the invariant; now it IS the
             control, and it was already written to be one. A refused row must not become the
             selection by ANY route — arrowing onto it in the radio group, a click, or a
             programmatic one — and React's controlled `checked` re-renders the input back
             from any of them because this never reports the change upward. Saving a voice
             the server is bound to refuse is the failure. */
          onChange={() => {
            if (!blocked) onChange(voice.id);
          }}
        />
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            {checked ? (
              <CheckCircle2 aria-hidden className="h-4 w-4 shrink-0 text-brand" />
            ) : (
              <span aria-hidden className="h-4 w-4 shrink-0 rounded-full border border-line" />
            )}
            <span className="text-sm font-semibold text-ink">{voice.label}</span>
            {voice.gender && (
              <span className="rounded-full border border-line px-2 py-0.5 text-[11px] font-medium text-ink-muted">
                {voice.gender}
              </span>
            )}
          </span>
          <span className="mt-0.5 block pl-6 text-xs text-ink-faint">
            {voice.languages.join(", ")}
            {voice.note ? ` · ${voice.note}` : ""}
          </span>
          {!voice.verified && (
            /* Stated, not hidden: the catalogue marks an entry verified only once the pilot
               has confirmed the engine accepts the string (OPERATIONS §2 gate 3). Choosing
               an unverified voice is allowed, and is a decision made knowingly. */
            <span className="mt-0.5 block pl-6 text-xs text-ink-faint">
              Not yet heard on a live call — verify it before a client does.
            </span>
          )}
          {blocked && (
            /* The server's own words, whole. Amber rather than muted because the reader
               skimming this list must not have to work out which rows are real. */
            <span
              id={reasonId}
              className="mt-0.5 block pl-6 text-xs font-medium text-amber-700 dark:text-amber-400"
            >
              Cannot be chosen — {voice.unavailable_reason ?? "this voice is not available here."}
            </span>
          )}
        </span>
      </label>
    );
  };

  // Voices with no server-sent tier name render first and ungrouped; the rest gather under
  // their label in first-appearance order, so the server's ordering survives the grouping.
  const ungrouped = voices.filter((voice) => tierLabel(voice) === null);
  const groups: { label: string; provider: string; rows: OfferedVoice[] }[] = [];
  for (const voice of voices) {
    const label = tierLabel(voice);
    if (label === null) continue;
    const group = groups.find((candidate) => candidate.label === label);
    if (group) group.rows.push(voice);
    else groups.push({ label, provider: voice.provider, rows: [voice] });
  }

  return (
    <fieldset>
      <legend className="text-xs font-medium text-ink-muted">{legend}</legend>
      {hint && <p className="mt-1 text-xs text-ink-faint">{hint}</p>}
      <div className="mt-2 space-y-4">
        {/* NO VOICES AT ALL — a real, correct and reachable state since D-588, and the one
            this component must not render as blank space under a hint.
            `agents/voices.py` no longer compiles a fallback catalogue: a deployment nobody
            has synced, or one where an operator has enabled nothing, offers none. What to
            do about it is the SERVER's sentence (`VoiceCatalogueOut.note`, which forks on
            which of those two it is and says whether reading the catalogue again would
            help) — the caller passes it as `hint` above, and this says out loud that the
            absence of rows is the subject rather than a list that failed to paint. */}
        {voices.length === 0 && (
          <p className="rounded-card border border-dashed border-line p-3 text-sm text-ink-muted">
            No voice is available to choose.
          </p>
        )}
        {ungrouped.length > 0 && <div className="space-y-2">{ungrouped.map(row)}</div>}
        {groups.map((group) => {
          const money = tierRateReading(rates, group.provider);
          const headingId = `${name}-tier-${group.label.toLowerCase().replace(/\s+/g, "-")}`;
          return (
            <div key={group.label} role="group" aria-labelledby={headingId}>
              {/* The rate sits OUTSIDE the labelling element deliberately: `aria-labelledby`
                  takes the whole subtree of the element it points at, so a price inside this
                  paragraph would be read into the group's accessible name and that name
                  would then change whenever the client's oldest lot changed. The heading
                  names the quality; the price is a sibling. */}
              <div className="flex flex-wrap items-baseline justify-between gap-2 pb-1">
                <p
                  id={headingId}
                  className="text-xs font-semibold uppercase tracking-wide text-ink-faint"
                >
                  {group.label} voice
                </p>
                {money && (
                  <span className="text-sm font-semibold tabular-nums text-ink">{money.rate}</span>
                )}
              </div>
              {money && <p className="pb-2 text-xs text-ink-faint">{money.note}</p>}
              <div className="space-y-2">{group.rows.map(row)}</div>
            </div>
          );
        })}
      </div>
    </fieldset>
  );
}
