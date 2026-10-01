/**
 * THE CHOICE CARD — a radio (or checkbox) rendered as a card, for a choice that matters
 * enough to show its options side by side with a line each. Shared by campaign creation,
 * the add-a-lead-source drawer and the add-a-destination drawer; one definition so the
 * three cannot drift.
 *
 * Usage: `<label className={`${CHOICE_CARD} ${on ? CHOICE_ON : CHOICE_OFF}`}>` around an
 * `sr-only` input and the option's text.
 */
/**
 * A radio rendered as a card.
 *
 * Selection is a brand ring plus a tick, NOT a brand fill. `--brand-soft` has no dark
 * value by design (it is the medallion tint, and `ui.tsx` uses it with a fixed dark-green
 * foreground), so a filled card would need its own text colour in each theme to stay
 * readable — a two-colour pair that the next person to add an option will get wrong. A
 * ring changes nothing about the text.
 */
/*
 * The FOCUS ring, on the card rather than on the input.
 *
 * The `<input type="radio">` inside each of these cards is `sr-only`, which deletes the
 * browser's own focus indicator — WCAG 2.4.7 Focus Visible (AA), failure technique F78,
 * exactly. `has-[:focus-visible]` puts it back on the label that hides it, so a keyboard
 * user tabbing into the group can see where they are; `focus-visible` rather than `focus`
 * so a mouse click does not leave a ring behind. `ring-offset-2` separates it from
 * `CHOICE_ON`'s selection ring, so "focused" and "chosen" stay two readable states.
 * `tests/contrast.test.ts` guards this at the source, because axe cannot evaluate a focus
 * indicator and jsdom has no layout to evaluate one in.
 */
export const CHOICE_CARD =
  "relative block cursor-pointer rounded-card border p-3 transition-colors " +
  "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-strong has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-app";
export const CHOICE_ON = "border-brand ring-1 ring-brand bg-surface";
export const CHOICE_OFF = "border-line bg-surface hover:border-ink-faint";
