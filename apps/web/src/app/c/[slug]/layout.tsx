"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { use, useState } from "react";
import {
  Bell,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  X,
} from "lucide-react";

import { BrandIcon } from "@/components/brand";

import { Providers } from "@/app/providers";
import { ToastProvider } from "@/components/interior/toaster";
import { SidebarSignOut } from "@/components/authn/sidebarSignOut";
import { NavDrawer } from "@/components/navDrawer";
import { ClientCopilotDock } from "@/components/copilot/CopilotDock";
import { OfflineBanner } from "@/components/offline";
import { Avatar, MAIN_CONTENT_ID, ProblemNotice, Skeleton, SkipLink } from "@/components/ui";
import { clientAuthn, CLIENT_SIGN_IN_PATH } from "@/lib/authn/clientAuthn";
import { ADMIN_CONSOLE_PATH } from "@/lib/authn/adminAuthn";
import { adminConsoleUrl } from "@/lib/consoleOrigin";
import { useAgreementsReadiness } from "@/lib/api/agreements";
import { useAttention } from "@/lib/api/attention";
import { useMe } from "@/lib/api/hooks";
import { ClientRealmProvider, useClientRealm } from "@/lib/api/session";
import { clientNavigation, type NavGroup, type NavItem } from "@/lib/clientNav";
import { currentNavItem } from "@/lib/nav";

/**
 * The client console's app shell.
 *
 * Every route under `/c/<slug>` renders inside it, so the things it gets wrong, it
 * gets wrong twenty times. Two of those are worth naming here because they are easy
 * to reintroduce: the nav is ONE list that both the sidebar and the page title read
 * (a second copy is how a renamed screen keeps its old title in the header), and
 * every destination in it is a route that exists — a nav entry pointing at a 404 is
 * the frontend's version of the half-wired feature `scripts/check_wiring.py` refuses
 * on the backend.
 */

/**
 * The nav entry this path belongs to — the ONE answer the header title and the sidebar
 * highlight both read.
 *
 * They used to be computed separately, four lines apart: the title by longest prefix and
 * the highlight by exact match. On `/calls/<id>` the header said "Call logs" while the
 * sidebar lit nothing and no element in the document carried `aria-current="page"`. The
 * rule itself now lives in `lib/nav.ts` because Next's route typing forbids exporting it
 * from a layout, and both shells needed the same one.
 */
function currentItem(groups: NavGroup[], pathname: string): NavItem | undefined {
  return currentNavItem(
    groups.flatMap((group) => group.items),
    pathname,
  );
}

function Sidebar({
  slug,
  isMobileOpen,
  onClose,
}: {
  slug: string;
  isMobileOpen: boolean;
  onClose: () => void;
}) {
  const pathname = usePathname();
  const { href, session } = useClientRealm();
  const me = useMe(session);
  const [isCollapsed, setIsCollapsed] = useState(false);
  // THE OUTSTANDING COUNT, injected rather than fetched inside `navigation()`, which is a
  // pure function the a11y sweep and `currentNavItem` walk without a provider. The number
  // is the SERVER's `outstanding_documents` and never a length computed here — the same
  // rule `lib/api/agreements.ts` states and `aiQuota.ts` argues: a browser that recounts a
  // list can disagree with the gate that refuses the dial.
  const readiness = useAgreementsReadiness(session);
  const outstanding = readiness.data?.outstanding_documents;
  const groups = clientNavigation(slug).map((group) => ({
    ...group,
    items: group.items.map((item) =>
      item.href.endsWith("/agreements") ? { ...item, badge: outstanding } : item,
    ),
  }));
  // The SAME entry the header names — see `currentItem`. Identity comparison rather than
  // a second match: two computations cannot disagree if there is only one.
  const current = currentItem(groups, pathname);

  const renderItem = (item: NavItem) => {
    const active = item === current;
    const Icon = item.icon;
    return (
      <Link
        key={item.href}
        href={href(item.href)}
        onClick={onClose}
        title={isCollapsed ? item.label : undefined}
        aria-current={active ? "page" : undefined}
        // `touch:min-h-11`: these are the console's primary navigation and the most-tapped
        // controls in the drawer, and `py-2` left them 36px tall — under the 44px finger
        // target, with only 4px of gap to the next one.
        className={`mb-1 flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors touch:min-h-11 ${
          active
            ? "bg-brand-soft text-brand-strong dark:bg-brand-strong/20 dark:text-brand-bright"
            : "text-ink-muted hover:bg-black/5 dark:hover:bg-white/5"
        } ${isCollapsed ? "justify-center" : ""}`}
      >
        <Icon className={`h-4 w-4 shrink-0 ${active ? "text-brand" : "text-ink-faint"}`} />
        {!isCollapsed && <span className="flex-1 truncate">{item.label}</span>}
        {/* Zero renders as NO badge rather than a "0", which reads like an unread marker
            — the bell's rule in `TopHeader`, applied here so the two cannot drift. While
            the read is in flight or has failed, `badge` is `undefined` and nothing
            renders: the sidebar does not get to claim there is nothing outstanding. */}
        {!isCollapsed && item.badge !== undefined && item.badge > 0 && (
          <span
            aria-label={`${item.badge} outstanding`}
            className="flex h-5 min-w-5 items-center justify-center rounded-full bg-rose-500 px-1.5 text-[10px] font-bold text-white"
          >
            {item.badge > 99 ? "99+" : item.badge}
          </span>
        )}
      </Link>
    );
  };

  return (
    <NavDrawer
      isOpen={isMobileOpen}
      onClose={onClose}
      label="Navigation"
      // `w-[255px]` in BOTH arms: `isCollapsed` is a desktop-only control, but it is
      // component state that SURVIVES a resize, so a collapsed sidebar carried the
      // mobile drawer into `lg:w-[72px]` with no base width at all — below `lg` the
      // panel then shrink-wrapped its content instead of being a 255px drawer. The
      // collapse is a desktop affordance; the drawer width is not its to change.
      className={isCollapsed ? "w-[255px] lg:w-[72px]" : "w-[255px]"}
    >
      <div className={`flex items-center p-5 ${isCollapsed ? "lg:justify-center lg:px-3" : "justify-between gap-3"}`}>
        <div className="flex items-center gap-3 overflow-hidden">
          {/* The chip is gone with the glyph — the mark is green ink, not a white icon. */}
          <BrandIcon size={36} />
          {/* `sr-only` rather than unmounted when collapsed: see the admin shell. */}
          <span className={isCollapsed ? "sr-only" : "whitespace-nowrap"}>
            <span className="block text-[17px] font-bold leading-none tracking-tight text-ink">
              Calevate
            </span>
            <span className="block text-[11px] font-medium text-ink-muted">AI agents</span>
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close navigation"
          className="flex items-center justify-center rounded-md p-1.5 text-ink-faint hover:bg-black/5 touch:h-11 touch:w-11 lg:hidden dark:hover:bg-white/5"
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
        {groups.map((group) => (
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

      {/* Who you are signed in AS. The design put a person's name and photo here;
          `/v1/me` returns the organization and the role and no name at all, so this
          shows what the server actually knows. An invented "John Carter" on a
          console an operator can also be impersonating into is worse than useless —
          it is the one place the screen must not be vague about whose account this
          is. */}
      <div className="border-t border-line p-4">
        <div className={`flex items-center rounded-lg p-2 ${isCollapsed ? "justify-center" : "gap-3"}`}>
          <Avatar name={me.data?.organization?.name ?? null} />
          {!isCollapsed &&
            /* `—` is an honest absence marker while the read is in flight and a
               PERMANENT, unexplained one after it fails: two dashes where the account
               name should be, on the one place in the shell that says whose account this
               is, and no way to tell "still loading" from "we lost the API". `TopHeader`
               and the admin shell's `HeldCount` both solved this by giving the failure a
               mark of its own, and this is the same answer in the same amber. */
            (me.error != null ? (
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-amber-700 dark:text-amber-400">
                  Account not read
                </p>
                <p className="truncate text-xs text-ink-muted">
                  Reload to see whose account this is
                </p>
              </div>
            ) : (
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-ink">
                  {me.data?.organization?.name ?? "—"}
                </p>
                <p className="truncate text-xs capitalize text-ink-muted">
                  {me.data?.role ?? "—"}
                </p>
              </div>
            ))}
        </div>
        {/* One control for BOTH client roles. The owner and the staff member see the same
            shell with different nav groups, so a role-specific sign-out would be two
            spellings of one thing — and the one person who must always be able to leave
            is the one whose role the server has not answered for yet. */}
        <SidebarSignOut
          authn={clientAuthn}
          signInPath={CLIENT_SIGN_IN_PATH}
          isCollapsed={isCollapsed}
        />
      </div>
    </NavDrawer>
  );
}

function TopHeader({ slug, onMenuToggle }: { slug: string; onMenuToggle: () => void }) {
  const pathname = usePathname();
  const { session, href } = useClientRealm();
  const attention = useAttention(session);
  const title = currentItem(clientNavigation(slug), pathname)?.label ?? "Dashboard";

  // The bell's count is the "needs attention" queue — the same number that screen
  // shows, from the same query. The design shipped it as a hardcoded 3; a badge that
  // always says 3 trains an owner to ignore the badge, which is the opposite of what
  // an alert is for. No count renders until the query answers, and zero renders as no
  // badge at all rather than a "0" that reads like an unread marker.
  //
  // `undefined`, never `?? 0`: the coalesce made a failed read indistinguishable from an
  // all-clear, which is the same "nobody is waiting" claim §52 exists to stop the shell
  // making. A bell that has lost the API says so.
  const waiting = attention.data?.total;

  return (
    <header className="sticky top-0 z-10 flex h-[72px] shrink-0 items-center justify-between border-b border-line bg-surface px-4 lg:px-8">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onMenuToggle}
          aria-label="Open navigation"
          className="flex h-9 w-9 items-center justify-center rounded-md text-ink-muted hover:bg-black/5 touch:h-11 touch:w-11 lg:hidden dark:hover:bg-white/5"
        >
          <Menu className="h-5 w-5" />
        </button>
        <h1 className="text-xl font-bold tracking-tight text-ink lg:text-2xl">{title}</h1>
      </div>

      <div className="flex items-center gap-2 lg:gap-4">
        <Link
          href={href(`/c/${slug}/attention`)}
          aria-label={
            attention.error != null
              ? "Needs attention: we could not read your queue"
              : waiting !== undefined && waiting > 0
                ? `Needs attention: ${waiting} item(s)`
                : "Needs attention"
          }
          className="relative flex h-9 w-9 items-center justify-center rounded-md border border-line bg-surface text-ink-muted hover:bg-black/5 touch:h-11 touch:w-11 dark:hover:bg-white/5"
        >
          <Bell className="h-4 w-4" />
          {attention.error != null ? (
            <span
              title="We could not read what needs your attention. Open the list to try again."
              className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full border-2 border-surface bg-amber-500 px-1 text-[9px] font-bold text-white"
            >
              ?
            </span>
          ) : (
            waiting !== undefined &&
            waiting > 0 && (
              <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full border-2 border-surface bg-rose-500 px-1 text-[9px] font-bold text-white">
                {waiting > 99 ? "99+" : waiting}
              </span>
            )
          )}
        </Link>
      </div>
    </header>
  );
}

function ViewAsBanner({ slug }: { slug: string }) {
  const { session, viewAsRequested } = useClientRealm();
  const me = useMe(session);

  if (me.data?.impersonating) {
    return (
      <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 bg-amber-500 px-4 py-1.5 text-center text-xs font-semibold text-amber-950">
        <span>
          Viewing as {me.data.organization?.name ?? slug} — read only. Every page view is
          logged, and anything that would change this account is refused.
        </span>
        {/* THE WAY OUT, and it belongs HERE rather than in the sidebar. There was none at
            all: an operator who had finished looking could only know to edit the URL, and
            the one control that looked like an exit — "Sign out" at the foot of the
            sidebar — ends the ADMIN session instead, dropping them at a sign-in page with
            a warning. So the sentence that says "you are impersonating" is now also the
            thing that stops it, which is the only place a reader is already looking.

            ABSOLUTE, through `adminConsoleUrl`: this banner only ever renders on the
            CLIENT hostname, and `app.` answers `location ^~ /admin { return 404; }`
            (`infra/nginx/calevate.conf.template`) — so the bare `/admin` this used to
            assign was a not-found screen for every operator who finished looking. The
            exact mirror of the view-as bug that produced `clientConsoleUrl`.

            A hard navigation, for `SidebarSignOut`'s reason: the in-memory grant cache
            (`admin.ts::grantCache`) and this tab's TanStack cache both hold another
            account's data, and a client-side route change would carry both into the admin
            console. `/admin` rather than the tenant's own page because this shell holds
            the SLUG and never the tenant id — inventing a lookup to land one screen
            deeper would be a request that can fail on the way out of a session. */}
        <button
          type="button"
          onClick={() => window.location.assign(adminConsoleUrl(ADMIN_CONSOLE_PATH))}
          className="shrink-0 rounded border border-amber-950/40 px-2 py-0.5 font-semibold underline-offset-2 hover:bg-amber-950/10 hover:underline"
        >
          Exit and return to the admin console
        </button>
      </div>
    );
  }

  // THE PENDING ARM, and it is a safety property rather than a polish item. The two arms
  // below cover "the server says you are impersonating" and "the read failed"; while the
  // read is IN FLIGHT `me.data` is undefined and `me.error` is null, so this component
  // rendered NOTHING — an operator sitting in a client's account with no marker at all,
  // on a console otherwise identical to that client's own. That was the visible half of
  // the `StepUpPrompt` deadlock (`lib/api/session.tsx`), where the read never resolved
  // and "in flight" lasted forever; the deadlock is fixed, but a slow read reproduces the
  // same unmarked screen and the marker must not depend on a request having answered.
  //
  // It states the INTENT, not the fact, and says which it is: the amber arm below quotes
  // the server's own `impersonating`, and this one must never be mistaken for it.
  if (viewAsRequested && me.isPending) {
    return (
      <div className="bg-amber-500/60 px-4 py-1.5 text-center text-xs font-semibold text-amber-950">
        Opening as an operator, read only — confirming with the server…
      </div>
    );
  }

  if (viewAsRequested && !me.data?.impersonating && me.error != null) {
    return (
      <div className="border-b border-rose-200 bg-rose-50 px-4 py-2 dark:border-rose-900 dark:bg-rose-950">
        <ProblemNotice error={me.error} />
        <p className="mt-2 text-xs text-rose-800 dark:text-rose-300">
          This page was opened as an operator. Open it from the admin console, or{" "}
          <Link href={`/c/${slug}`} className="underline">
            continue as a normal user
          </Link>
          .
        </p>
      </div>
    );
  }

  return null;
}

export default function ClientRealmLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ slug: string }>;
}) {
  const { slug } = use(params);
  const [isMobileOpen, setIsMobileOpen] = useState(false);

  return (
    <Providers>
      {/* `ToastProvider` app-wide for this realm, so `useToast()` works on any screen the
          shell renders. Its notifications region is `fixed` bottom-right, renders AFTER the
          shell subtree and is `pointer-events-none` with an empty `aria-live` polite region
          until a toast is fired — so it adds no landmark the a11y sweep flags, no focusable
          element ahead of `SkipLink`, and nothing to the DOM the "you are here" checks read.
          It wraps the shell (rather than sitting inside the scrolling `<main>`) so a toast
          survives navigation between screens and is not clipped by the shell's overflow. */}
      <ToastProvider>
        {/* `data-app-shell` is what `globals.css` scopes its `overflow: hidden` pin to.
            The document scrolls by default; a shell that clips its own content is the only
            thing that needs the document to stop. */}
        <div data-app-shell className="fixed inset-0 flex overflow-hidden bg-app font-sans">
          {/* FIRST focusable thing in the shell, and outside `ClientRealmProvider` on
              purpose: the sidebar is 21 links, and a reader must be able to bypass them
              even while the session is still resolving and the fallback skeleton is what
              is on screen (WCAG 2.4.1, Level A). */}
          <SkipLink />
          <ClientRealmProvider
            slug={slug}
            fallback={
              // A `<main>` here too, carrying the same id: `SkipLink` above is rendered in
              // EVERY state of this shell, so its target has to exist in every state or the
              // control is dead exactly when the page is slowest. The gate branches get
              // theirs from `SessionGate`'s `landmark` prop; this is the Suspense arm, which
              // no gate reaches. Measured by axe in a real browser — `skip-link`, "the
              // skip-link target should exist and be focusable".
              <main
                id={MAIN_CONTENT_ID}
                tabIndex={-1}
                className="flex h-full w-full items-center justify-center"
              >
                <div className="w-96">
                  <Skeleton rows={8} />
                </div>
              </main>
            }
          >
            <Sidebar slug={slug} isMobileOpen={isMobileOpen} onClose={() => setIsMobileOpen(false)} />
            <div className="flex flex-1 flex-col overflow-hidden">
              {/* ABOVE the view-as banner and the header, because it is a statement about
                  the whole window rather than about this screen — and it renders nothing at
                  all while online, so a connected user pays no DOM for it. */}
              <OfflineBanner />
              <ViewAsBanner slug={slug} />
              <TopHeader slug={slug} onMenuToggle={() => setIsMobileOpen(true)} />
              {/* `tabIndex={-1}` is what makes `SkipLink` actually skip: following a
                  fragment scrolls to the target but only MOVES FOCUS if the target is
                  focusable, so without it the next Tab resumes inside the navigation the
                  reader just asked to leave. */}
              <main
                id={MAIN_CONTENT_ID}
                tabIndex={-1}
                className="relative flex-1 overflow-y-auto px-4 py-4 lg:px-8 lg:py-6"
              >
                <div className="mx-auto max-w-[1280px]">{children}</div>
              </main>
            </div>
            {/* The screen assistant. INSIDE `ClientRealmProvider`, because it reads the
                realm session through `useClientSession()` — and therefore also carries a
                view-as session unchanged when an operator is looking. Outside the
                scrolling `<main>` so its `fixed` panel is not clipped. It renders nothing
                until the screen on show declares itself. */}
            <ClientCopilotDock />
          </ClientRealmProvider>
        </div>
      </ToastProvider>
    </Providers>
  );
}
