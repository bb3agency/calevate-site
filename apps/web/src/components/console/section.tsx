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
 * The quiet text action a section or a row carries: "Change", "View all", "Add another".
 * A link-looking button rather than a bordered one, because on a calm screen the only
 * filled control is the primary action and the only bordered ones are secondary buttons.
 */
export const TEXT_ACTION =
  "press inline-flex items-center gap-1 rounded-sm text-body font-medium text-brand-strong dark:text-brand-bright hover:underline underline-offset-2 disabled:cursor-not-allowed disabled:opacity-50 disabled:no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11";

/** The same, for the one destructive text action a row may carry ("Remove"). */
export const TEXT_ACTION_DANGER =
  "press inline-flex items-center gap-1 rounded-sm text-body font-medium text-danger hover:underline underline-offset-2 disabled:cursor-not-allowed disabled:opacity-50 disabled:no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger touch:min-h-11";
