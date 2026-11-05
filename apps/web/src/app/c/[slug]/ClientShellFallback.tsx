"use client";

import { usePathname } from "next/navigation";

import { BrandIcon } from "@/components/brand";
import { SIDEBAR_ROW_CLASS, sidebarNavClass } from "@/components/sidebarCollapse";
import { MAIN_CONTENT_ID, SHELL_MAIN_CLASS, SHELL_RAIL_CLASS, Skeleton } from "@/components/ui";
import { clientNavigation } from "@/lib/clientNav";
import { clientPageTitle } from "@/lib/clientPageTitle";

import { currentItem } from "./ClientSidebar";

/**
 * The console's frame while the session is being checked: the sidebar, the top bar with
 * this page's name, and a skeleton only where the page goes.
 *
 * A bare skeleton in an empty window read as a blank site on a slow phone. The frame needs
 * no session (the nav is `clientNavigation(slug)`, a pure function), so it can be drawn at
 * once. Its rows are plain text, not links: until the session is known there is no view-as
 * parameter to carry, and the real sidebar replaces this one a moment later.
 */
export function ClientShellFallback({ slug }: { slug: string }) {
  const pathname = usePathname();
  const groups = clientNavigation(slug);
  const current = currentItem(groups, pathname);

  return (
    <>
      <aside
        aria-hidden
        className="hidden w-[255px] shrink-0 flex-col border-r border-line bg-surface lg:flex"
      >
        <div className="flex items-center gap-3 px-[18px] pt-5 pb-3">
          <BrandIcon size={36} />
          <span>
            <span className="block text-[17px] font-bold leading-none tracking-tight text-ink">Calevate</span>
            <span className="block text-[11px] font-medium text-ink-muted">AI agents</span>
          </span>
        </div>
        <div className={sidebarNavClass}>
          {groups.map((group) => (
            <div key={group.heading ?? "main"} className="mb-4">
              {group.heading && (
                <span className="mb-1 block px-4 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
                  {group.heading}
                </span>
              )}
              {group.items.map((item) => {
                const Icon = item.icon;
                const active = item === current;
                return (
                  <span
                    key={item.href}
                    className={`${SIDEBAR_ROW_CLASS} ${
                      active
                        ? "bg-brand-soft text-brand-strong dark:bg-brand-strong/20 dark:text-brand-bright"
                        : "text-ink-muted"
                    }`}
                  >
                    <Icon className={`h-4 w-4 shrink-0 ${active ? "text-brand" : "text-ink-faint"}`} />
                    <span className="truncate">{item.label}</span>
                  </span>
                );
              })}
            </div>
          ))}
        </div>
      </aside>
      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="sticky top-0 z-header flex h-[72px] shrink-0 items-center border-b border-line bg-surface px-3 sm:px-4 lg:px-8">
          <div className={`${SHELL_RAIL_CLASS} flex items-center gap-3`}>
            <span className="lg:hidden">
              <BrandIcon size={32} />
            </span>
            <span className="line-clamp-2 text-heading text-ink [overflow-wrap:anywhere] sm:line-clamp-1 sm:text-title">{clientPageTitle(slug, pathname)}</span>
          </div>
        </header>
        {/* A `<main>` with the shell's id: `SkipLink` renders in every state of the shell,
            so its target must exist in every state too (WCAG 2.4.1). */}
        <main id={MAIN_CONTENT_ID} tabIndex={-1} className={SHELL_MAIN_CLASS}>
          <div className={SHELL_RAIL_CLASS}>
            <Skeleton rows={8} />
          </div>
        </main>
      </div>
    </>
  );
}
