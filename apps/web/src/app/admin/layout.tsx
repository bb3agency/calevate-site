"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ComponentType } from "react";
import {
  Building2,
  HeartPulse,
  Hourglass,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  ShieldCheck,
  SlidersHorizontal,
  UserPlus,
  X,
} from "lucide-react";

import { Providers } from "@/app/providers";
import { NOTICE_TONES } from "@/components/ui";
import { useHeldTenants } from "@/lib/api/admin";

/**
 * Admin realm shell — `admin.calevate.tech`.
 *
 * A SEPARATE route group from `/c/[slug]` on purpose (TRD §11): different Clerk
 * application, different session, different navigation. Nothing here imports the client
 * realm's session helpers — no `ClientRealmProvider`, no `useClientRealm`, no
 * `devSession` — so an admin token and a client token cannot be confused by a shared
 * code path. The one thing the two shells share is the design language, which is in
 * `globals.css` and `components/ui.tsx` and carries no session at all.
 *
 * It is built to feel like the client shell's SIBLING rather than its copy: the same
 * grouped sidebar, the same 72px sticky header, the same one-list-drives-the-title rule.
 * Three things are deliberately different, and each is a safety property rather than a
 * decoration:
 *
 * 1. **The medallion is `brand-strong`, not `brand`, and it is a shield.** An operator
 *    with cross-client reach must never be one glance away from believing they are
 *    inside a client's own dashboard — the same instinct behind D-22's impersonation
 *    banner, applied to the console they start from.
 * 2. **A persistent cross-client marker sits in the header**, at every route, saying
 *    what this session can see. The client shell's header carries the client's own
 *    notification bell; this one carries the fact that nothing here is one client.
 * 3. **There is no identity block naming a person.** See `IdentityFooter`.
 *
 * The previous shell was `min-h-full` inside a `body` that `globals.css` gives
 * `overflow: hidden` — so a long admin table could not be scrolled to the bottom at all.
 * The `fixed inset-0` shell the client realm already uses is what makes the main panel
 * own its own scrolling, which is why the migration is a fix and not only a repaint.
 */

interface NavItem {
  href: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
}

interface NavGroup {
  /** Null for the primary group, which carries no heading. */
  heading: string | null;
  items: NavItem[];
}

/**
 * ONE list. The sidebar renders it and the header title is derived from it, so a screen
 * that is renamed cannot keep its old name in the header — the defect a second copy
 * always eventually produces.
 *
 * The health board and the hold queue sit beside Clients rather than being reachable only
 * from a client row, and for the same reason in both cases: the account quietly failing,
 * or held on a gate nobody has looked at, is precisely the one nobody navigates to
 * (`admin/health.py`, `admin/holds.py`). Discovery must not depend on already knowing
 * which client to open.
 */
const NAV: NavGroup[] = [
  {
    heading: null,
    items: [
      { href: "/admin", label: "Clients", icon: Building2 },
      { href: "/admin/health", label: "Client health", icon: HeartPulse },
      { href: "/admin/holds", label: "Held accounts", icon: Hourglass },
    ],
  },
  {
    heading: "Onboarding",
    items: [{ href: "/admin/new", label: "New client", icon: UserPlus }],
  },
  {
    heading: "Platform",
    items: [{ href: "/admin/ops", label: "Operations", icon: SlidersHorizontal }],
  },
];

/**
 * The heading the header shows, taken from the SAME list the sidebar renders.
 *
 * Longest match wins, so `/admin/tenants/<id>/kyc` keeps "Clients" (the section it
 * belongs to) rather than falling through, and `/admin/new` keeps its own name instead of
 * inheriting `/admin`'s — which is what a plain `startsWith` in list order would give.
 *
 * Not exported: Next's route-file typing rejects any export from a `layout.tsx` that is
 * not one of its own conventions (`OmitWithTag` in `.next/types`), and a helper that has
 * to leave the file to be tested would be a second copy of the nav list waiting to happen.
 * It is asserted through the rendered header instead, which is what a reader sees anyway.
 */
function currentTitle(pathname: string): string {
  let best: NavItem | undefined;
  for (const item of NAV.flatMap((group) => group.items)) {
    if (pathname === item.href || pathname.startsWith(`${item.href}/`)) {
      if (!best || item.href.length > best.href.length) best = item;
    }
  }
  return best?.label ?? "Clients";
}

function Sidebar({ isMobileOpen, onClose }: { isMobileOpen: boolean; onClose: () => void }) {
  const pathname = usePathname();
  const [isCollapsed, setIsCollapsed] = useState(false);

  const renderItem = (item: NavItem) => {
    const active = pathname === item.href;
    const Icon = item.icon;
    return (
      <Link
        key={item.href}
        href={item.href}
        onClick={onClose}
        title={isCollapsed ? item.label : undefined}
        aria-current={active ? "page" : undefined}
        className={`mb-1 flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
          active
            ? "bg-brand-soft text-brand-strong dark:bg-brand-strong/20 dark:text-brand-bright"
            : "text-ink-muted hover:bg-black/5 dark:hover:bg-white/5"
        } ${isCollapsed ? "justify-center" : ""}`}
      >
        <Icon className={`h-4 w-4 shrink-0 ${active ? "text-brand" : "text-ink-faint"}`} />
        {!isCollapsed && <span className="flex-1 truncate">{item.label}</span>}
      </Link>
    );
  };

  return (
    <>
      {isMobileOpen && (
        <button
          type="button"
          aria-label="Close navigation"
          className="fixed inset-0 z-40 bg-ink/40 backdrop-blur-sm lg:hidden"
          onClick={onClose}
        />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-50 flex shrink-0 flex-col border-r border-line bg-surface transition-transform duration-300 lg:static lg:translate-x-0 ${
          isCollapsed ? "lg:w-[72px]" : "w-[255px]"
        } ${isMobileOpen ? "translate-x-0" : "-translate-x-full"}`}
      >
        <div
          className={`flex items-center p-5 ${
            isCollapsed ? "lg:justify-center lg:px-3" : "justify-between gap-3"
          }`}
        >
          <div className="flex items-center gap-3 overflow-hidden">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-strong text-white">
              <ShieldCheck className="h-5 w-5" />
            </span>
            {!isCollapsed && (
              <span className="whitespace-nowrap">
                <span className="block text-[17px] font-bold leading-none tracking-tight text-ink">
                  Calevate admin
                </span>
                <span className="block text-[11px] font-medium text-ink-muted">
                  Operator console
                </span>
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close navigation"
            className="flex items-center justify-center rounded-md p-1.5 text-ink-faint hover:bg-black/5 lg:hidden dark:hover:bg-white/5"
          >
            <X className="h-5 w-5" />
          </button>
          {!isCollapsed && (
            <button
              type="button"
              onClick={() => setIsCollapsed(true)}
              aria-label="Collapse sidebar"
              className="hidden shrink-0 items-center justify-center rounded-md p-1.5 text-ink-faint hover:bg-black/5 lg:flex dark:hover:bg-white/5"
            >
              <PanelLeftClose className="h-4 w-4" />
            </button>
          )}
        </div>

        {isCollapsed && (
          <div className="hidden justify-center pb-2 lg:flex">
            <button
              type="button"
              onClick={() => setIsCollapsed(false)}
              aria-label="Expand sidebar"
              className="flex items-center justify-center rounded-md p-1.5 text-ink-faint hover:bg-black/5 dark:hover:bg-white/5"
            >
              <PanelLeftOpen className="h-4 w-4" />
            </button>
          </div>
        )}

        <nav className="custom-scrollbar relative flex-1 overflow-y-auto px-3 py-4">
          {NAV.map((group) => (
            <div key={group.heading ?? "main"} className="mb-6">
              {group.heading &&
                (isCollapsed ? (
                  <div className="mx-2 mb-3 h-px bg-line" />
                ) : (
                  <h3 className="mb-3 px-3 text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
                    {group.heading}
                  </h3>
                ))}
              {group.items.map(renderItem)}
            </div>
          ))}
        </nav>

        <IdentityFooter isCollapsed={isCollapsed} />
      </aside>
    </>
  );
}

/**
 * What this console knows about the session it is running in — which is the REALM, and
 * nothing else.
 *
 * The client shell puts the organization and the role here, read from `/v1/me`. The admin
 * realm has no such endpoint: `/v1/me` resolves through `current_any`, which only reaches
 * the admin realm when the `X-Impersonate-Org` header is present (`core/auth.py`), so an
 * admin token asking it is refused as a client token. There is therefore no honest way
 * for this shell to print an operator's name, role or permissions today.
 *
 * So it prints the one thing that IS true and matters most — that this session is not
 * inside any single client — rather than an invented name. An operator console that shows
 * a plausible identity it did not verify is worse than one that shows none: it is the
 * exact surface where "whose account am I in" must never be a guess. The gap is recorded
 * in the report accompanying this change; the block gains a name and a role the day an
 * admin-realm identity read exists.
 */
function IdentityFooter({ isCollapsed }: { isCollapsed: boolean }) {
  return (
    <div className="border-t border-line p-4">
      <div className={`flex items-center rounded-lg p-2 ${isCollapsed ? "justify-center" : "gap-3"}`}>
        <span
          aria-hidden
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-strong"
        >
          <ShieldCheck className="h-4 w-4" />
        </span>
        {!isCollapsed && (
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-ink">Admin realm</p>
            <p className="truncate text-xs text-ink-muted">Signed in across every client</p>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * The header's one number: how many accounts are waiting on a human right now.
 *
 * The client shell's bell shows that client's attention queue; the operator's equivalent
 * is the hold queue, and it is the number an operator should not have to navigate to find
 * — a held account is invisible precisely because nobody opens it (`admin/holds.py`).
 *
 * It reuses `useHeldTenants`, so it shares the queue screen's cache entry and its poll
 * rather than adding a second request for the same list. Nothing renders until the query
 * answers, and a FAILED read renders no badge rather than a zero: "nobody is waiting" is
 * the one claim this queue must never make from a failure, and a `0` in a shell chrome is
 * that claim in its most trusted form.
 */
function HeldCount() {
  const queue = useHeldTenants();
  const waiting = queue.data?.length ?? 0;

  return (
    <Link
      href="/admin/holds"
      aria-label={
        waiting > 0 ? `Held accounts: ${waiting} waiting on us` : "Held accounts"
      }
      className="relative flex h-9 w-9 items-center justify-center rounded-md border border-line bg-surface text-ink-muted hover:bg-black/5 dark:hover:bg-white/5"
    >
      <Hourglass className="h-4 w-4" />
      {waiting > 0 && (
        <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full border-2 border-surface bg-rose-500 px-1 text-[9px] font-bold text-white">
          {waiting > 99 ? "99+" : waiting}
        </span>
      )}
    </Link>
  );
}

function TopHeader({ onMenuToggle }: { onMenuToggle: () => void }) {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-10 flex h-[72px] shrink-0 items-center justify-between border-b border-line bg-surface px-4 lg:px-8">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onMenuToggle}
          aria-label="Open navigation"
          className="flex h-9 w-9 items-center justify-center rounded-md text-ink-muted hover:bg-black/5 lg:hidden dark:hover:bg-white/5"
        >
          <Menu className="h-5 w-5" />
        </button>
        {/* The screens themselves carry no `<h1>`: the title lives here, derived from the
            nav, so it cannot say one thing in the sidebar and another on the page. */}
        <h1 className="text-xl font-bold tracking-tight text-ink lg:text-2xl">
          {currentTitle(pathname)}
        </h1>
      </div>

      <div className="flex items-center gap-2 lg:gap-4">
        {/* The marker, at every route. Not a `NoticeBox`: that component is a verdict about
            something the reader must act on, and this is a standing statement about the
            session. It borrows the same warn palette so the two never disagree on tone. */}
        <span
          className={`hidden rounded-full border px-3 py-1 text-[11px] font-semibold sm:inline-block ${NOTICE_TONES.warn}`}
        >
          Cross-client · every action is audited
        </span>
        <HeldCount />
      </div>
    </header>
  );
}

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const [isMobileOpen, setIsMobileOpen] = useState(false);

  return (
    <Providers>
      <div className="fixed inset-0 flex overflow-hidden bg-app font-sans">
        <Sidebar isMobileOpen={isMobileOpen} onClose={() => setIsMobileOpen(false)} />
        <div className="flex flex-1 flex-col overflow-hidden">
          <TopHeader onMenuToggle={() => setIsMobileOpen(true)} />
          <main className="relative flex-1 overflow-y-auto px-4 py-4 lg:px-8 lg:py-6">
            <div className="mx-auto max-w-[1280px]">{children}</div>
          </main>
        </div>
      </div>
    </Providers>
  );
}
