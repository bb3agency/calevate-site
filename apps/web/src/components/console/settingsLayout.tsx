"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
} from "react";

import { ConfirmDialog } from "@/components/confirmDialog";
import { useTabs } from "@/components/interior/tabs";
import { ScrollRegion } from "@/components/ui";
import { UnsavedRegistry, type UnsavedRegistryValue } from "@/lib/useUnsavedGuard";

export type SettingsSection = {
  /** URL value: `?section=<id>`. Lowercase, stable — people bookmark and share these. */
  id: string;
  label: string;
  /** A small count or state beside the label ("2", a dot). Decorative text is fine. */
  badge?: ReactNode;
  /** One line of state under the label in the column menu ("5 steps · changes waiting"). */
  detail?: string;
  /** A section that lives on its own page: the menu links there instead of `?section=`. */
  href?: string;
};

/** The search param that holds the open section, unless a screen needs another name. */
export const SECTION_PARAM = "section";

const NO_ALIASES: Readonly<Record<string, string>> = {};

/**
 * A link to another section from outside the menu (the agent header's "Try it"), taking the
 * same unsaved-edits guard as the menu: while a form in the open section is dirty, following
 * it opens the "Leave without saving?" dialog instead of switching. Only a `header` passed to
 * the layout can reach it; anywhere else it is `null` and the caller keeps a plain link.
 */
export type SectionLink = {
  href: string;
  /** For a link: lets it navigate, or holds it while there are unsaved edits. */
  onClick: (event: MouseEvent<HTMLAnchorElement>) => void;
  /** For a menu item that is not a link: switches, or asks first. */
  go: () => void;
};

const SectionLinks = createContext<((id: string) => SectionLink) | null>(null);

export function useSectionLink(id: string): SectionLink | null {
  const linkTo = useContext(SectionLinks);
  return linkTo ? linkTo(id) : null;
}

/**
 * Which section is open: the URL's, when it names one of `sections` (directly or through
 * `aliases`); otherwise the first. Exported so a screen can read the same answer (for its
 * copilot surface, say) without a second parse.
 */
export function useActiveSection(
  sections: SettingsSection[],
  param = SECTION_PARAM,
  aliases: Readonly<Record<string, string>> = NO_ALIASES,
): string {
  const params = useSearchParams();
  const asked = params.get(param);
  const wanted = asked !== null && Object.hasOwn(aliases, asked) ? aliases[asked] : asked;
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
 * `menu="tabs"` (D-825) draws the sections as a WAI-ARIA tab list over one panel, for a
 * screen with a few peer parts that each want the full width (the agent page). It keeps the
 * URL, the unsaved-edits guard and the one-mounted-section rule above. Two things differ
 * from the link menu:
 *
 * - Manual activation: the arrow keys move focus and Enter or Space opens the tab. The APG
 *   recommends automatic activation only when a panel shows without delay; each of these
 *   panels mounts its own reads, so arrowing across them would fire requests per key press
 *   (w3.org/WAI/ARIA/apg/patterns/tabs, "Keyboard Interaction").
 * - No entry fade and no focus move on a switch: focus stays on the tab, as the pattern
 *   expects, and a switch that may come from the keyboard is not animated.
 *
 * `aliases` maps section ids a screen no longer has to the one that now holds their
 * content, so a bookmarked `?section=test` still opens where testing lives.
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
  aliases,
  header,
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
   * "tabs": a tab list above the panel at every width. Sections with `href` are not drawn.
   */
  menu?: "column" | "row" | "tabs";
  aliases?: Readonly<Record<string, string>>;
  /** Drawn above the menu, where `useSectionLink` works. */
  header?: ReactNode;
  className?: string;
}) {
  const pathname = usePathname();
  const params = useSearchParams();
  const inPlace = sections.filter((s) => !s.href);
  const active = useActiveSection(inPlace, param, aliases);
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
  const linkTo = (id: string): SectionLink => ({
    href: hrefFor(id),
    onClick: (event) => {
      if (id === active || drafts.current.size === 0) return;
      event.preventDefault();
      setPending(id);
    },
    go: () => {
      if (id === active) return;
      if (drafts.current.size > 0) setPending(id);
      else router.push(hrefFor(id), { scroll: false });
    },
  });

  const confirm =
    pending !== null ? (
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
          picked.current = menu !== "tabs";
          router.push(hrefFor(to), { scroll: false });
        }}
      >
        <p>Your changes in {current?.label ?? "this section"} have not been saved.</p>
      </ConfirmDialog>
    ) : null;

  if (menu === "tabs") {
    return (
      <SectionLinks.Provider value={linkTo}>
        {header}
        <TabbedSections
          label={label}
          sections={inPlace}
          active={active}
          className={className}
          onPick={(id) => linkTo(id).go()}
        >
          <UnsavedRegistry.Provider value={registry}>{renderSection(active)}</UnsavedRegistry.Provider>
          {confirm}
        </TabbedSections>
      </SectionLinks.Provider>
    );
  }

  return (
    <SectionLinks.Provider value={linkTo}>
      {header}
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
        {confirm}
      </div>
    </SectionLinks.Provider>
  );
}

/**
 * The tab list and the one panel under it. The look is the kit's underline tabs
 * (`interior/tabs`): a row of words on a hairline, the open one in ink and medium weight
 * with a brand underline, so the open tab differs by weight and line as well as colour.
 * On a phone the row scrolls sideways inside a named `ScrollRegion` rather than wrapping
 * into a second row, and the open tab is brought into view when the page opens on it.
 */
function TabbedSections({
  label,
  sections,
  active,
  onPick,
  className,
  children,
}: {
  label: string;
  sections: SettingsSection[];
  active: string;
  onPick: (id: string) => void;
  className: string;
  children: ReactNode;
}) {
  const items = useMemo(() => sections.map((s) => ({ value: s.id, label: s.label })), [sections]);
  const tabs = useTabs({ items, value: active, onValueChange: onPick, activation: "manual" });
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const bring = () => {
      const list = listRef.current;
      const tab = list?.querySelector<HTMLElement>('[aria-selected="true"]');
      const region = list?.parentElement;
      if (!tab || !region) return;
      // Scrolled inside the row only: `scrollIntoView` would also move the page.
      const box = region.getBoundingClientRect();
      const at = tab.getBoundingClientRect();
      if (at.left < box.left) region.scrollLeft -= box.left - at.left + 16;
      else if (at.right > box.left + region.clientWidth) region.scrollLeft += at.right - (box.left + region.clientWidth) + 16;
    };
    bring();
    // Measured again whenever the row changes width (the web font arriving, a badge
    // appearing once its count is read), or the open tab can end up half off the row.
    if (typeof ResizeObserver === "undefined" || !listRef.current) return;
    const watch = new ResizeObserver(bring);
    watch.observe(listRef.current);
    return () => watch.disconnect();
  }, [active]);

  const current = sections.find((s) => s.id === active);
  return (
    <div className={className}>
      <ScrollRegion
        label={label}
        className="-mx-4 border-b border-line px-4 [scrollbar-width:none] sm:mx-0 sm:px-0 [&::-webkit-scrollbar]:hidden"
      >
        <div ref={listRef} {...tabs.tabListProps} aria-label={label} className="flex w-max gap-5 pr-4 sm:gap-6 sm:pr-0">
          {sections.map((section, index) => {
            const selected = section.id === active;
            return (
              <button
                key={section.id}
                {...tabs.getTabProps({ value: section.id, label: section.label }, index)}
                className={`-mb-px flex h-11 shrink-0 items-center gap-1.5 border-b-2 text-body outline-none transition-colors duration-(--duration-fast) focus-visible:rounded-sm focus-visible:ring-2 focus-visible:ring-brand ${
                  selected ? "border-brand-strong font-medium text-ink" : "border-transparent text-ink-muted hover:text-ink"
                }`}
              >
                {section.label}
                {section.badge !== undefined && (
                  <span className="rounded-full bg-warn/15 px-1.5 text-[12px] font-medium tabular-nums text-ink">
                    {section.badge}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </ScrollRegion>
      <div key={active} {...tabs.getPanelProps(active)} className="min-w-0 pt-6 outline-none focus-visible:ring-2 focus-visible:ring-brand">
        {/* The panel is named by its tab; this heading puts it in the heading outline. */}
        <h2 className="sr-only">{current?.label}</h2>
        {children}
      </div>
    </div>
  );
}
