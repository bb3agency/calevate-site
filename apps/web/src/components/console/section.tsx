import type { ReactNode } from "react";

import { InfoTip } from "./infoTip";

/**
 * A HEADED BLOCK OF A SCREEN, WITH NO BOX AROUND IT.
 *
 * UX-DOCTRINE §1 already says a block that is prose, facts or one homogeneous list is a
 * plain `<section>`, not a `Card`; this is that section written once, so screens stop
 * reaching for a card because it was the only thing with a heading. Whitespace separates
 * sections (the screen stacks them `space-y-10`); hairlines separate rows inside one.
 *
 * - `title` is the user's question or job ("Calls today", "Accounts your agents use"),
 *   never our schema's noun.
 * - `description` is ONE line. Reasoning belongs behind an ⓘ (`InfoTip`), not here.
 * - `info` is the reasoning behind an ⓘ beside the title (D-657). Never a compliance
 *   sentence or an error: those stay visible.
 * - `action` is a quiet link or secondary button about this block ("View all", "Add").
 *   The screen's one primary action never lives here (doctrine §4).
 * - `headingLevel` is 2 for a block on a page and 3 inside a settings section, whose
 *   label `SettingsLayout` already prints as the `h2`.
 */
export function Section({
  title,
  description,
  info,
  action,
  headingLevel = 2,
  children,
  className = "",
}: {
  title: ReactNode;
  description?: ReactNode;
  info?: ReactNode;
  action?: ReactNode;
  headingLevel?: 2 | 3;
  children?: ReactNode;
  className?: string;
}) {
  const Heading = headingLevel === 3 ? "h3" : "h2";
  return (
    // Unnamed on purpose, as `Card` is: a named <section> is a region landmark, and a
    // screen of ten landmarks (some echoing a table's own region name) is noise, not
    // navigation. The heading carries the structure.
    <section className={className}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <div className="flex min-w-0 items-center gap-1">
          <Heading className="text-heading text-ink">
            {title}
          </Heading>
          {info ? <InfoTip label={typeof title === "string" ? title : "this section"}>{info}</InfoTip> : null}
        </div>
        {action ? <div className="flex shrink-0 items-center gap-3">{action}</div> : null}
      </div>
      {description ? (
        <p className="mt-1 max-w-prose text-body text-ink-muted [text-wrap:pretty]">{description}</p>
      ) : null}
      {children !== undefined ? <div className="mt-4">{children}</div> : null}
    </section>
  );
}

/**
 * THE TERTIARY BUTTON a section or a row carries: "Change", "View all", "Skip for now".
 * Three ranks, one look each: the filled primary, the bordered secondary, and this, a
 * borderless button with the button's own shape (padding, radius, a tinted hover and press
 * ground). It used to be underlined green text, which on a calm screen read as a stray link
 * rather than a control (founder, 23 Oct 2026). Give it an icon when the verb is not enough
 * to recognise it at a glance (a plus to add, an arrow to move on, a cross to put aside).
 *
 * Optically aligned: the negative inline margin puts the label, not the padding, on the
 * column's left edge, so a row of these lines up with the text above. Inside a running
 * sentence use a plain link instead; a padded control there breaks the line.
 */
export const TEXT_ACTION =
  "press -mx-2 inline-flex min-h-8 items-center gap-1.5 rounded-md px-2 text-body font-medium text-brand-strong transition-colors duration-(--duration-fast) dark:text-brand-bright [&:not(:disabled)]:hover:bg-brand-soft dark:[&:not(:disabled)]:hover:bg-white/5 [&:not(:disabled)]:active:bg-brand-soft disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11";

/** The same, for the one destructive action a row may carry ("Remove"). */
export const TEXT_ACTION_DANGER =
  "press -mx-2 inline-flex min-h-8 items-center gap-1.5 rounded-md px-2 text-body font-medium text-danger transition-colors duration-(--duration-fast) [&:not(:disabled)]:hover:bg-danger-soft [&:not(:disabled)]:active:bg-danger-soft disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger touch:min-h-11";
