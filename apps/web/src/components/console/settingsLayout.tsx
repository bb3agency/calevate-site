"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { ConfirmDialog } from "@/components/confirmDialog";
import { ScrollRegion } from "@/components/ui";
import { UnsavedRegistry, type UnsavedRegistryValue } from "@/lib/useUnsavedGuard";

export type SettingsSection = {
  /** URL value: `?section=<id>`. Lowercase, stable — people bookmark and share these. */
  id: string;
  label: string;
  /** A small count or state beside the label ("2", a dot). Decorative text is fine. */
  badge?: ReactNode;
  /** One line of state under the label in the column menu ("5 sections · changes waiting"). */
  detail?: string;
  /** A section that lives on its own page: the menu links there instead of `?section=`. */
  href?: string;
};

/** The search param that holds the open section, unless a screen needs another name. */
export const SECTION_PARAM = "section";

/**
 * Which section is open: the URL's, when it names one of `sections`; otherwise the first.
 * Exported so a screen can read the same answer (for its copilot surface, say) without a
 * second parse.
 */
export function useActiveSection(sections: SettingsSection[], param = SECTION_PARAM): string {
  const params = useSearchParams();
  const wanted = params.get(param);
  return sections.some((s) => s.id === wanted) ? (wanted as string) : (sections[0]?.id ?? "");
}

/**
 * A SCREEN OF SETTINGS AN OWNER VISITS ONE PART AT A TIME (D-657): a section menu — a left
 * column from `lg`, a scrolling row at the top on a phone — and one section's content.
 *
 * WHY A SEARCH PARAM AND NOT A ROUTE SEGMENT. `?section=voice` keeps every section on ONE
 * route: the screen's queries, its unsaved drafts and its copilot surface stay mounted
 * while the reader moves between sections, and adding a section is an entry in an array.
 * A `[section]` segment would make each section its own page module (D-196: a page may
 * export only `default`), remount the screen on every switch and drop any unsaved draft,
 * and spread one screen across a folder per section. The URL still addresses each section
 * — it can be bookmarked, shared, reloaded and reached with Back — which is the property
 * the segment would have bought.
 *
 * The menu is links, not tabs: a section has its own URL and Back returns to the previous
 * one. Other search params (the operator's `view_as`) are carried over. When a reader
 * picks a section, focus moves to its heading so a keyboard or screen-reader user lands
 * on what they asked for; a section opened from the URL on first load does not steal
 * focus.
 *
 * ONLY THE OPEN SECTION IS MOUNTED, and a switch asks first when it would lose typing.
 * Keeping every section mounted and hidden was the alternative, and it is the wrong one
 * here: a section that declares a copilot surface (the captured-details editor does)
 * would declare it at page load and, since the registry's newest entry wins, answer for
 * whichever section is actually on screen. So sections mount and unmount cleanly, and any
 * form inside one that uses `useUnsavedGuard` reports its draft to this layout; while one
 * is dirty, choosing another section opens a confirm dialog instead of switching. (The
 * browser's Back button changes the URL without asking; the guard's `beforeunload` half
 * still covers a reload or a closed tab.)
 *
 * Never put a compliance control or its qualifying sentence in a section other than the
 * one that opens first (UX-DOCTRINE §8.7).
 */
export function SettingsLayout({
  label,
  sections,
  renderSection,
  param = SECTION_PARAM,
  menu = "column",
  className = "",
}: {
  /** Names the section menu: "Agent settings". */
  label: string;
  sections: SettingsSection[];
  renderSection: (id: string) => ReactNode;
  param?: string;
  /**
   * "column" (default): a sticky left column from `lg`, a scrolling row of pills below it.
   * "row": the scrolling row at every width — for a layout nested inside another page's
   * own section column, where a second column would leave the content too narrow.
   */
  menu?: "column" | "row";
  className?: string;
}) {
  const pathname = usePathname();
  const params = useSearchParams();
  const active = useActiveSection(sections.filter((s) => !s.href), param);
  const row = menu === "row";
  const router = useRouter();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const picked = useRef(false);
  // Which guarded forms in the open section hold unsaved edits.
  const drafts = useRef(new Set<string>());
  const registry = useMemo<UnsavedRegistryValue>(
    () => ({
      report: (id, dirty) => {
        if (dirty) drafts.current.add(id);
        else drafts.current.delete(id);
      },
    }),
    [],
  );
  // The section somebody asked for while a draft was open, awaiting their answer.
  const [pending, setPending] = useState<string | null>(null);

  useEffect(() => {
    if (!picked.current) return;
    picked.current = false;
    headingRef.current?.focus({ preventScroll: false });
  }, [active]);

  const hrefFor = (id: string) => {
    const next = new URLSearchParams(params.toString());
    next.set(param, id);
    return `${pathname}?${next.toString()}`;
  };
  const current = sections.find((s) => s.id === active);

  return (
    <div className={`${row ? "" : "gap-8 lg:grid lg:grid-cols-[200px_minmax(0,1fr)]"} ${className}`}>
      {/* ONE list of links in both shapes — a scrolling row of pills on a phone, a sticky
          column from `lg` — so each section has exactly one link in the document. */}
      <nav aria-label={label} className={row ? "mb-5" : "mb-5 lg:sticky lg:top-2 lg:mb-0 lg:self-start"}>
        <ScrollRegion
          label={label}
          className={`-mx-1 px-1 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden ${row ? "" : "lg:mx-0 lg:overflow-visible lg:p-0"}`}
        >
          <ul className={row ? "flex w-max gap-1" : "flex w-max gap-1 lg:w-auto lg:flex-col lg:gap-0.5"}>
            {sections.map((section) => {
              const on = section.id === active;
              return (
                <li key={section.id}>
                  <Link
                    href={section.href ?? hrefFor(section.id)}
                    scroll={false}
                    aria-current={on ? "true" : undefined}
                    aria-describedby={section.detail && !row ? `${param}-${section.id}-detail` : undefined}
                    onClick={(event) => {
                      if (on || section.href) return;
                      if (drafts.current.size > 0) {
                        event.preventDefault();
                        setPending(section.id);
                        return;
                      }
                      picked.current = true;
                    }}
                    className={`press flex min-h-9 items-center gap-2 whitespace-nowrap lg:py-1.5 rounded-full px-3.5 text-[13px] font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11 ${row ? "" : "lg:justify-between lg:rounded-md lg:px-3 lg:text-[14px]"} ${
                      on
                        ? row
                          ? "bg-ink text-surface"
                          : "bg-ink text-surface lg:bg-ink/[0.06] lg:text-ink"
                        : row
                          ? "text-ink-muted hover:bg-ink/[0.05] hover:text-ink"
                          : "text-ink-muted hover:bg-ink/[0.05] hover:text-ink lg:font-normal"
                    }`}
                  >
                    <span className="min-w-0">
                      <span className="block truncate">{section.label}</span>
                      {section.detail && !row && (
                        // Described, not named: the link's name stays the section's name.
                        <span
                          id={`${param}-${section.id}-detail`}
                          aria-hidden
                          className="hidden truncate text-[12px] font-normal text-ink-faint lg:block"
                        >
                          {section.detail}
                        </span>
                      )}
                    </span>
                    {section.badge !== undefined && (
                      <span
                        className={`text-[12px] tabular-nums ${on ? (row ? "text-surface/80" : "text-surface/80 lg:text-ink-faint") : "text-ink-faint"}`}
                      >
                        {section.badge}
                      </span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </ScrollRegion>
      </nav>
      <section aria-labelledby={`settings-${active}`} className="min-w-0">
        <h2
          id={`settings-${active}`}
          ref={headingRef}
          tabIndex={-1}
          className="mb-4 text-[17px] font-semibold text-ink focus-visible:outline-none"
        >
          {current?.label}
        </h2>
        {/* Keyed by section so a switch is a fresh mount: no state leaks between sections,
            and the entry fade plays once per switch (reduced motion: none). */}
        <div key={active} className="settings-enter">
          <UnsavedRegistry.Provider value={registry}>{renderSection(active)}</UnsavedRegistry.Provider>
        </div>
      </section>
      {pending !== null && (
        <ConfirmDialog
          title="Leave without saving?"
          confirmLabel="Discard changes"
          pendingLabel="Discarding…"
          cancelLabel="Keep editing"
          pending={false}
          error={null}
          onCancel={() => setPending(null)}
          onConfirm={() => {
            const to = pending;
            setPending(null);
            drafts.current.clear();
            picked.current = true;
            router.push(hrefFor(to), { scroll: false });
          }}
        >
          <p>Your changes in {current?.label ?? "this section"} have not been saved.</p>
        </ConfirmDialog>
      )}
    </div>
  );
}
