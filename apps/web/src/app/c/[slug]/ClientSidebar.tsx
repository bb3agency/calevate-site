"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { UserRound } from "lucide-react";

import { SidebarSignOut } from "@/components/authn/sidebarSignOut";
import { NavDrawer } from "@/components/navDrawer";
import {
  SIDEBAR_FOOTER_CLASS,
  SIDEBAR_IDENTITY_ROW_CLASS,
  SIDEBAR_ROW_CLASS,
  SidebarBrand,
  SidebarGroupHeading,
  SidebarLabel,
  sidebarFadeClass,
  sidebarNavClass,
  sidebarPanelClass,
  useSidebarCollapse,
} from "@/components/sidebarCollapse";
import { Avatar } from "@/components/ui";
import { clientAuthn, CLIENT_ACCOUNT_PATH, CLIENT_SIGN_IN_PATH } from "@/lib/authn/clientAuthn";
import { useAgreementsReadiness } from "@/lib/api/agreements";
import { useMe } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { clientNavigation, type NavGroup, type NavItem } from "@/lib/clientNav";
import { currentNavItem } from "@/lib/nav";

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
export function currentItem(groups: NavGroup[], pathname: string): NavItem | undefined {
  return currentNavItem(
    groups.flatMap((group) => group.items),
    pathname,
  );
}

export function ClientSidebar({
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
  const { isCollapsed, toggle } = useSidebarCollapse();
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
        // Geometry (padding, the 44px finger target, the clip that keeps a collapsing row
        // from pushing its icon off centre) is `SIDEBAR_ROW_CLASS`, shared with the admin
        // shell so the two consoles' rows cannot drift apart or animate differently.
        className={`${SIDEBAR_ROW_CLASS} transition-colors ${
          active
            ? "bg-brand-soft text-brand-strong dark:bg-brand-strong/20 dark:text-brand-bright"
            : "text-ink-muted hover:bg-ink/[0.04] hover:text-ink"
        }`}
      >
        <Icon className={`h-4 w-4 shrink-0 ${active ? "text-brand" : "text-ink-faint"}`} />
        {/* MOUNTED IN BOTH STATES, faded and clipped rather than removed — see
            `components/sidebarCollapse.tsx`. It used to be `{!isCollapsed && …}`, which
            both popped (the label vanished a frame before anything moved) and took all 21
            destination names out of the accessibility tree for a collapsed reader. */}
        <SidebarLabel isCollapsed={isCollapsed}>{item.label}</SidebarLabel>
        {/* Zero renders as NO badge rather than a "0", which reads like an unread marker
            — the bell's rule in `TopHeader`, applied here so the two cannot drift. While
            the read is in flight or has failed, `badge` is `undefined` and nothing
            renders: the sidebar does not get to claim there is nothing outstanding. */}
        {item.badge !== undefined && item.badge > 0 && (
          <span
            aria-label={`${item.badge} outstanding`}
            className={`flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-danger px-1.5 text-[10px] font-bold text-white ${sidebarFadeClass(
              isCollapsed,
            )}`}
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
      // Width, the width TRANSITION, and the rule that the mobile drawer keeps a base
      // width of its own whatever `isCollapsed` holds — all one expression, shared with
      // the admin shell. See `components/sidebarCollapse.tsx`.
      className={sidebarPanelClass(isCollapsed)}
    >
      <SidebarBrand
        isCollapsed={isCollapsed}
        onClose={onClose}
        onToggle={toggle}
        title="Calevate"
        subtitle="AI agents"
      />

      <nav className={sidebarNavClass}>
        {groups.map((group) => (
          <div key={group.heading ?? "main"} className="mb-4">
            {group.heading && (
              <SidebarGroupHeading isCollapsed={isCollapsed}>{group.heading}</SidebarGroupHeading>
            )}
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
      <div className={SIDEBAR_FOOTER_CLASS}>
        <div className={SIDEBAR_IDENTITY_ROW_CLASS}>
          <Avatar name={me.data?.organization?.name ?? null} />
          {/* `—` is an honest absence marker while the read is in flight and a
              PERMANENT, unexplained one after it fails: two dashes where the account
              name should be, on the one place in the shell that says whose account this
              is, and no way to tell "still loading" from "we lost the API". `TopHeader`
              and the admin shell's `HeldCount` both solved this by giving the failure a
              mark of its own, and this is the same answer in the same amber.

              `<span className="block">` rather than `<p>`: `SidebarLabel` is a `<span>`
              (it has to be — its other call sites are inside `<a>` and `<button>`, where
              a block-level label is the wrong element), and a `<p>` inside a `<span>` is
              invalid markup that the parser silently unnests. */}
          <SidebarLabel isCollapsed={isCollapsed}>
            {me.error != null ? (
              <>
                <span className="block truncate text-sm font-semibold text-warn">
                  Account not read
                </span>
                <span className="block truncate text-xs text-ink-muted">
                  Reload to see whose account this is
                </span>
              </>
            ) : (
              <>
                {/* TRUNCATION STAYS and the value is made reachable instead: the panel
                    is a fixed 255px and a business name is arbitrary ("Sri Lakshmi
                    Multispeciality Dental Clinic"), so nothing short enough to fit is
                    honest. `title` is the minimum that makes the cut recoverable; it is
                    omitted while the read is in flight, because "—" is not a name. */}
                <span
                  title={me.data?.organization?.name ?? undefined}
                  className="block truncate text-sm font-semibold text-ink"
                >
                  {me.data?.organization?.name ?? "—"}
                </span>
                <span className="block truncate text-xs capitalize text-ink-muted">
                  {me.data?.role ?? "—"}
                </span>
              </>
            )}
          </SidebarLabel>
        </div>
        {/* THE WAY TO YOUR OWN LOGIN, and it had no door from in here at all.
            `/auth/account` is where a signed-in person verifies their address, changes
            their password and ends every other session — and until this link existed the
            only route to it was the marketing header, which nobody sees once they are
            working in the console. A shipped control nobody can reach is the half-wired
            defect in its quietest form: everything works, and no client ever finds it.

            NOT in `clientNavigation()`, deliberately: every entry there is a `/c/<slug>`
            route (`lib/copilot/navigate.ts` relies on exactly that to decide what the
            assistant may open), and this one belongs to neither slug nor console. It sits
            with the sign-out because that is the other thing on this shell that is about
            the PERSON rather than about the business, and it is styled as its twin so the
            collapsed rail keeps one column of glyphs. */}
        <Link
          href={CLIENT_ACCOUNT_PATH}
          title={isCollapsed ? "Your account" : undefined}
          className="flex w-full items-center gap-3 overflow-hidden rounded-lg px-4 py-1.5 text-body font-medium text-ink-muted transition-colors hover:bg-ink/[0.04] hover:text-ink touch:min-h-11"
        >
          <UserRound aria-hidden className="h-4 w-4 shrink-0" />
          {/* Mounted and faded rather than unmounted, for `SidebarSignOut`'s reason: the
              accessible name survives the collapsed rail. */}
          <SidebarLabel isCollapsed={isCollapsed}>Your account</SidebarLabel>
        </Link>
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
