"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ComponentType } from "react";
import {
  Building2,
  ClipboardCheck,
  HeartPulse,
  Hourglass,
  Lock,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  PhoneOff,
  ShieldCheck,
  SlidersHorizontal,
  UserPlus,
  X,
} from "lucide-react";

import { adminAccess, useAdminMe } from "@/app/admin/access";
import { Providers } from "@/app/providers";
import { NavDrawer } from "@/components/navDrawer";
import { NOTICE_TONES, NoticeBox } from "@/components/ui";
import { useHeldTenants } from "@/lib/api/admin";
import { ApiProblem } from "@/lib/api/client";
import { AdminRealmClerkProvider } from "@/lib/auth/adminRealm";

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
  /**
   * The permission the screen behind this entry actually needs — the one its own routes
   * declare (`openapi_extra=permission_meta(...)`), not a guess about seniority.
   */
  permission: string;
  /** What the entry lets you do, completing "…so you cannot ___" in the refusal. */
  action: string;
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
 *
 * Each entry carries the PERMISSION its screen needs, taken from the routes that screen
 * calls: the directory and the wizard are `admin:tenants` (`admin/routes.py`), the health
 * board and the hold queue are `org:read` (their modules argue why a read of a work list
 * is not the authority to act on it), and Operations is `ops:manage` — which only
 * `superadmin` holds (`core/rbac.py`), so every route that screen calls refuses an
 * `operator`. That entry is the reason this list grew a permission column at all: it was
 * offered to every admin role, and an operator following it got a page that is nothing
 * but a 403.
 */
const NAV: NavGroup[] = [
  {
    heading: null,
    items: [
      {
        href: "/admin",
        label: "Clients",
        icon: Building2,
        permission: "admin:tenants",
        action: "open the client directory",
      },
      {
        href: "/admin/health",
        label: "Client health",
        icon: HeartPulse,
        permission: "org:read",
        action: "open the client health board",
      },
      {
        href: "/admin/holds",
        label: "Held accounts",
        icon: Hourglass,
        permission: "org:read",
        action: "open the hold queue",
      },
      {
        href: "/admin/qa-sampling",
        label: "QA sampling",
        icon: ClipboardCheck,
        permission: "org:read",
        action: "open the QA sampling queue",
      },
    ],
  },
  {
    heading: "Onboarding",
    items: [
      {
        href: "/admin/new",
        label: "New client",
        icon: UserPlus,
        permission: "admin:tenants",
        action: "create clients",
      },
    ],
  },
  {
    heading: "Platform",
    items: [
      {
        href: "/admin/ops",
        label: "Operations",
        icon: SlidersHorizontal,
        permission: "ops:manage",
        action: "open the operations console",
      },
      {
        // Its own entry rather than a panel on Operations, and the reason is discovery
        // rather than layout: whoever is handling a regulator's complaint is following
        // `runbooks/dnc-complaint.md`, not scrolling a screen of platform switches — and
        // the longest-match title rule below means `/admin/ops/dnc` keeps this name
        // instead of inheriting "Operations".
        href: "/admin/ops/dnc",
        label: "Global do-not-call",
        icon: PhoneOff,
        permission: "ops:manage",
        action: "change the platform-wide do-not-call list",
      },
    ],
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

/**
 * An entry this session cannot use is SHOWN AND DEAD, never hidden — and the choice is
 * the console's existing doctrine rather than a preference.
 *
 * The client realm never hides a control the session may not use: `useWriteAccess` +
 * `RestrictionNote` disable it and print why (`lib/api/hooks.ts`), and `/c/[slug]/usage`
 * — a whole SCREEN a `staff` member may not read — keeps its nav entry and answers with a
 * sentence rather than vanishing from the sidebar. Three things make that the right
 * default here too:
 *
 * 1. **A console whose shape depends on the viewer cannot be talked about.** "Open
 *    Operations and halt outbound" is a sentence one operator says to another during an
 *    incident; an entry that is simply absent reads as a broken build, and the next move
 *    is a support ticket about missing navigation rather than a message to a superadmin.
 * 2. **Hiding buys no security.** The API is the enforcement (`requires()` on every
 *    route), the role table is in the repo, and the permission name is the most useful
 *    part of the refusal — it is what the operator has to ask for.
 * 3. **It is one mechanism, not two.** The controls INSIDE these screens are disabled
 *    with their reason; a nav that hid instead would mean the console answered the same
 *    question two different ways depending on where you asked it.
 *
 * The one case that must not be treated as a refusal is not knowing: see `adminAccess`,
 * where navigation deliberately fails OPEN.
 */
function Sidebar({ isMobileOpen, onClose }: { isMobileOpen: boolean; onClose: () => void }) {
  const pathname = usePathname();
  const [isCollapsed, setIsCollapsed] = useState(false);
  // ONE identity read for the whole nav — `adminAccess` is a pure verdict on it, so the
  // number of entries can change without breaking the rules of hooks.
  const me = useAdminMe();

  const renderItem = (item: NavItem) => {
    const active = pathname === item.href;
    const Icon = item.icon;
    const access = adminAccess(me, item.permission, item.action);

    // `refused`, not `!allowed`: while the identity read is in flight, and if it FAILED,
    // every entry stays a live link. Nothing appears or disappears under the pointer, and
    // an unreadable identity cannot lock an operator out of a console whose ops surface is
    // never load-shed for exactly that reason (BACKEND-PATTERNS §6).
    if (access.refused) {
      return (
        <div key={item.href} className="mb-1">
          <span
            aria-disabled="true"
            title={access.reason ?? item.label}
            className={`flex cursor-not-allowed items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-ink-faint ${
              isCollapsed ? "justify-center" : ""
            }`}
          >
            <Icon className="h-4 w-4 shrink-0 text-ink-faint" />
            {!isCollapsed && (
              <>
                <span className="flex-1 truncate">{item.label}</span>
                <Lock aria-hidden className="h-3.5 w-3.5 shrink-0" />
              </>
            )}
          </span>
          {/* Beside the dead entry, not only in a `title` a mouse has to discover: a
              greyed-out label with no sentence is indistinguishable from a broken build. */}
          {!isCollapsed && access.reason && (
            <p className="px-3 pb-1 text-[11px] leading-snug text-ink-faint">{access.reason}</p>
          )}
        </div>
      );
    }

    return (
      <Link
        key={item.href}
        href={item.href}
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
      </Link>
    );
  };

  return (
    <NavDrawer
      isOpen={isMobileOpen}
      onClose={onClose}
      label="Admin navigation"
      // `w-[255px]` in BOTH arms: `isCollapsed` is a desktop-only control, but it is
      // component state that SURVIVES a resize, so a collapsed sidebar carried the
      // mobile drawer into `lg:w-[72px]` with no base width at all — below `lg` the
      // panel then shrink-wrapped its content instead of being a 255px drawer. The
      // collapse is a desktop affordance; the drawer width is not its to change.
      className={isCollapsed ? "w-[255px] lg:w-[72px]" : "w-[255px]"}
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
    </NavDrawer>
  );
}

/**
 * What this console knows about the session it is running in — the REALM, and now the
 * ROLE the server says it has.
 *
 * The role arrives from `GET /v1/admin/me` (`admin/routes.py`), which is what this block
 * was waiting for: until that route existed, `/v1/me` resolved through `current_any` and
 * reached the admin realm only when `X-Impersonate-Org` was present (`core/auth.py`), so
 * an admin token asking it was refused as a client token and there was no honest way to
 * print anything about the operator at all.
 *
 * Still no NAME, and that is not an omission: the identity document deliberately carries
 * none (`MeOut` carries none either), because a console that displays a plausible identity
 * it did not verify is worse than one that displays none — this is the exact surface where
 * "whose account am I in" must never be a guess. Until the answer lands, the line says the
 * one thing that is true regardless: this session is not inside any single client.
 */
function IdentityFooter({ isCollapsed }: { isCollapsed: boolean }) {
  // Same query key as the nav's, so this shares that request rather than adding one.
  const me = useAdminMe();
  const role = me.data?.role;

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
            <p className="truncate text-xs text-ink-muted">
              {role ? `${role} · signed in across every client` : "Signed in across every client"}
            </p>
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
 * answers, and a `0` in shell chrome would be "nobody is waiting" in its most trusted
 * form — the one claim this queue must never make from a failure.
 *
 * The `?? 0` that used to stand here made exactly that claim, quietly. It collapsed "we
 * do not know" into "none", which the badge then rendered as no badge — the same pixels
 * an all-clear produces. §52's second clause is that failure is a REFUSAL, and nothing is
 * not a refusal: an operator whose console has lost the API sees a calm header. So the
 * unknown case is now its own mark, and the label says which of the two it is.
 */
function HeldCount() {
  const queue = useHeldTenants();
  /** `undefined` = no answer yet. Never coalesced: see above. */
  const waiting = queue.data?.length;

  return (
    <Link
      href="/admin/holds"
      aria-label={
        queue.error != null
          ? "Held accounts: we could not read the queue"
          : waiting !== undefined && waiting > 0
            ? `Held accounts: ${waiting} waiting on us`
            : "Held accounts"
      }
      className="relative flex h-9 w-9 items-center justify-center rounded-md border border-line bg-surface text-ink-muted hover:bg-black/5 touch:h-11 touch:w-11 dark:hover:bg-white/5"
    >
      <Hourglass className="h-4 w-4" />
      {queue.error != null ? (
        <span
          title="We could not read the hold queue. Open Holds to try again."
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
          className="flex h-9 w-9 items-center justify-center rounded-md text-ink-muted hover:bg-black/5 touch:h-11 touch:w-11 lg:hidden dark:hover:bg-white/5"
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

/**
 * The console, behind the ADMIN Clerk application.
 *
 * This is the edit `app/(auth)/admin/sign-in/…/page.tsx` names as "the one remaining
 * one": mounting the admin application on the sign-in page let an operator sign IN, but
 * nothing put that session on the rest of `/admin/**`. Against a real Clerk deployment
 * every screen here called `/v1/admin/*` with a credential `adminRealmToken` could not
 * produce, so the whole surface was a wall of `AuthProblem` refusals — correct, in that
 * it never fell back to anything, and useless, in that the sign-in page that would have
 * fixed it was one nobody was sent to.
 *
 * `protect` is what sends them: `<Show when="signed-in" fallback={<RedirectToSignIn/>}>`
 * inside `AdminRealmClerkProvider`, which redirects to `ADMIN_SIGN_IN_PATH` and renders
 * null (not the fallback) while clerk-js is still deciding — so a signed-in operator
 * never flashes a redirect on the way in.
 *
 * Three things this deliberately does NOT do:
 *
 * 1. **It does not share a line of session logic with the client realm.** The import is
 *    `lib/auth/adminRealm`, whose twin `clientRealm` it never touches — two Clerk
 *    applications, two publishable keys, two cookies (CLAUDE.md conventions, TRD §11,
 *    D-37). `lib/api/session.tsx` mounts the client realm's provider the same way for
 *    `/c/<slug>`; that this file reads like that one is the shape of the rule, not a
 *    shared helper waiting to be extracted — a `realm` parameter on one provider is one
 *    bad conditional away from presenting an admin credential on a client surface.
 * 2. **It does not wrap the sign-in page.** `/admin/sign-in` lives in `app/(auth)/`, off
 *    this layout's filesystem chain, precisely so this `protect` cannot redirect a
 *    signed-out operator into a page it would itself protect — an infinite redirect.
 *    That file's own docstring is the other half of this comment.
 * 3. **It changes nothing about a local run.** `AdminRealmClerkProvider` returns
 *    `children` untouched when `AUTH_MODE === "dev"` (lib/auth/mode.ts: unset variable
 *    outside a production build), so with no Clerk keys configured the console renders
 *    exactly the tree it rendered before and keeps speaking `dev:admin:` — no provider,
 *    no clerk-js, no network. `tests/adminAuth.test.tsx` pins that, because "the console
 *    still works locally" is the property this edit could most easily have broken.
 *
 * The provider sits OUTSIDE `Providers` on purpose. Everything below it makes
 * authenticated calls the moment it mounts — `useAdminMe` and `useHeldTenants` fire from
 * the shell itself — and a QueryClient mounted above the auth gate would start those
 * queries for someone on their way to the sign-in page.
 */
/**
 * What an operator sees when the API refuses their session for want of a second factor.
 *
 * ## This is an EXPLANATION, never the gate
 *
 * The gate is `apps/api/core/auth.py::verify_token`, which refuses every admin-realm
 * token whose Clerk session did not complete a second factor (`fva[1] == -1`). Nothing
 * in this file makes anything safe: a browser that skipped this component would get 403
 * `mfa_required` on every single request instead of a sentence, which is precisely the
 * failure this removes. `tests/admin_mfa_test.py` is where the property lives.
 *
 * ## Why it hangs off the identity read rather than off a Clerk hook
 *
 * `useAdminMe()` is the first authenticated call this shell makes, on every route, and
 * it goes through the same verifier as everything else — so the answer it gets IS the
 * deployment's real MFA policy, including the `mfa_claim_missing` case where the admin
 * Clerk application is misconfigured and the browser has no way to know. Reading
 * `user.twoFactorEnabled` from clerk-js instead would render this panel from the
 * BROWSER's opinion of the session, which can be true while the API still refuses (a
 * session signed in before enrolment, a token minted from a template without `fva`) and
 * false while it does not. The refusal that matters is the server's, so that is the one
 * that speaks.
 *
 * It REPLACES the console rather than sitting above it: every panel underneath would
 * otherwise render its own 403, and a screen that half-works against an API refusing
 * every call is worse than one honest page (`clerkRuntime.tsx` makes the same choice for
 * an unconfigured realm).
 */
export const MFA_PROBLEM_CODES = ["mfa_required", "mfa_claim_missing"] as const;

function AdminMfaGate({ children }: { children: React.ReactNode }) {
  const me = useAdminMe();
  const problem = me.error instanceof ApiProblem ? me.error : null;
  const refused =
    problem !== null && (MFA_PROBLEM_CODES as readonly string[]).includes(problem.code);

  if (!refused || problem === null) return <>{children}</>;

  return (
    <div className="mx-auto max-w-xl p-6">
      <NoticeBox
        tone="stop"
        icon={<Lock aria-hidden className="h-4 w-4" />}
        title="Two-step verification required"
      >
        <p className="mt-1">{problem.message}</p>
        {problem.remediation && <p className="mt-2">{problem.remediation}</p>}
        <p className="mt-2 text-xs">
          The operator console holds cross-client data and the platform controls, so this
          is required of every admin account — it is not something this screen can waive.
        </p>
      </NoticeBox>
    </div>
  );
}

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const [isMobileOpen, setIsMobileOpen] = useState(false);

  return (
    <AdminRealmClerkProvider protect>
      <Providers>
        <AdminMfaGate>
          {/* `data-app-shell` is what `globals.css` scopes its `overflow: hidden` pin
              to. The document scrolls by default; a shell that clips its own content is
              the only thing that needs the document to stop. */}
          <div data-app-shell className="fixed inset-0 flex overflow-hidden bg-app font-sans">
            <Sidebar isMobileOpen={isMobileOpen} onClose={() => setIsMobileOpen(false)} />
            <div className="flex flex-1 flex-col overflow-hidden">
              <TopHeader onMenuToggle={() => setIsMobileOpen(true)} />
              <main className="relative flex-1 overflow-y-auto px-4 py-4 lg:px-8 lg:py-6">
                <div className="mx-auto max-w-[1280px]">{children}</div>
              </main>
            </div>
          </div>
        </AdminMfaGate>
      </Providers>
    </AdminRealmClerkProvider>
  );
}
