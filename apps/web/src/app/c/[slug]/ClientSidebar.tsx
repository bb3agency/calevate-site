"use client";

import { BuildStamp } from "@/components/UpdateWatcher";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronDown, UserRound } from "lucide-react";
import { useCallback, useEffect, useId, useState, type ReactNode } from "react";

import { SidebarSignOut } from "@/components/authn/sidebarSignOut";
import { NavDrawer } from "@/components/navDrawer";
import {
  SIDEBAR_FOOTER_CLASS,
  SIDEBAR_IDENTITY_ROW_CLASS,
  SIDEBAR_ROW_CLASS,
  SidebarBrand,
  SidebarGroupBody,
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
import { useFirstRun } from "@/lib/api/firstRun";
import { useMe } from "@/lib/api/hooks";
import { seatLabel } from "@/lib/api/members";
import { BELL_ROWS, unseenAttention, useNotifications } from "@/lib/api/notifications";
import { useClientRealm } from "@/lib/api/session";
import { useTrialPanel } from "@/lib/api/trialCalls";
import { useLeadNouns } from "@/lib/businessCapabilities";
import {
  clientNavigation,
  inAccountWords,
  showsTrialNav,
  trialNavigation,
  type NavGroup,
  type NavItem,
} from "@/lib/clientNav";
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

/**
 * The current page's row: full ink on a faint ink well, in weight as well as colour. Not the
 * brand green, which the palette keeps for money and things done; a selected row is neither.
 * `text-ink` holds well over 4.5:1 on both page grounds, and the well is under 10% ink.
 */
export const SELECTED_ROW = "bg-ink/[0.07] font-semibold text-ink";
export const SELECTED_ICON = "text-ink";

/** A badge's fill: the text tokens, so the white count on them keeps 4.5:1. */
const BADGE_FILL: Record<NonNullable<NavItem["badgeTone"]>, string> = {
  warn: "bg-warn",
  stop: "bg-danger",
};

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
  // Problems not seen yet, from the header bell's own query (same key, no extra request):
  // opening the bell or the queue marks them seen and the badge drops. Unresolved problems
  // stay listed on the screen itself.
  const waiting = unseenAttention(useNotifications(session, BELL_ROWS).data);
  // THE SHORT TRIAL SIDEBAR until the first test minute (founder, 28 Nov 2026). The
  // agreements are asked for where they matter, in the Hear-it step's ticks, so the trial
  // view carries no outstanding count; the server's gate is untouched by what is drawn here.
  const trial = useTrialPanel(session);
  const trialView = showsTrialNav(trial.data);
  const firstRun = useFirstRun(session, trialView && !session.impersonateOrg);
  const groups = inAccountWords(clientNavigation(slug), slug, useLeadNouns()).map((group) => ({
    ...group,
    items: group.items.map((item): NavItem =>
      item.href.endsWith("/agreements")
        ? trialView
          ? item
          : { ...item, badge: outstanding, badgeTone: "stop" }
        : item.href.endsWith("/attention")
          ? { ...item, badge: waiting, badgeTone: "warn" }
          : item,
    ),
  }));
  // The SAME entry the header names — see `currentItem`. Compared by `href`, because the
  // trial list relabels the agents entry into a copy of it.
  const current = currentItem(groups, pathname);
  const [closed, setClosed] = useState<ReadonlySet<string>>(new Set());
  const everything = useShowEverything();

  const renderItem = (item: NavItem, to: string = item.href) => {
    const active = item.href === current?.href;
    const Icon = item.icon;
    return (
      <Link
        key={item.href}
        href={href(to)}
        onClick={onClose}
        title={isCollapsed ? item.label : undefined}
        aria-current={active ? "page" : undefined}
        // Geometry (padding, the 44px finger target, the clip that keeps a collapsing row
        // from pushing its icon off centre) is `SIDEBAR_ROW_CLASS`, shared with the admin
        // shell so the two consoles' rows cannot drift apart or animate differently.
        className={`${SIDEBAR_ROW_CLASS} transition-colors ${
          active
            ? SELECTED_ROW
            : "text-ink-muted hover:bg-ink/[0.04] hover:text-ink"
        }`}
      >
        <span className="relative flex shrink-0">
          <Icon className={`h-4 w-4 shrink-0 ${active ? SELECTED_ICON : "text-ink-faint"}`} />
          {/* The collapsed rail fades the count out with the label, so the icon keeps a
              dot in the badge's colour: the rail still says something is waiting. */}
          {item.badge !== undefined && item.badge > 0 && (
            <span
              aria-hidden
              className={`absolute -right-1 -top-1 size-2 rounded-full ring-2 ring-surface ${BADGE_FILL[item.badgeTone ?? "stop"]} ${
                isCollapsed ? "opacity-0 lg:opacity-100" : "opacity-0"
              }`}
            />
          )}
        </span>
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
            className={`flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full px-1.5 text-[10px] font-bold text-white ${BADGE_FILL[item.badgeTone ?? "stop"]} ${sidebarFadeClass(
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
        {trialView ? (
          <TrialNav
            slug={slug}
            groups={groups}
            current={current}
            agentsTo={firstRun.data?.due === true ? `/c/${slug}/agents/first` : undefined}
            everything={everything}
            isCollapsed={isCollapsed}
            renderItem={renderItem}
          />
        ) : (
          <GroupedNav
            groups={groups}
            current={current}
            closed={isCollapsed ? NONE_CLOSED : closed}
            onToggle={(heading) =>
              setClosed((was) => {
                const next = new Set(was);
                if (!next.delete(heading)) next.add(heading);
                return next;
              })
            }
            isCollapsed={isCollapsed}
            renderItem={renderItem}
          />
        )}
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
                <span className="block truncate text-xs text-ink-muted">
                  {seatLabel(me.data) ?? "—"}
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
          className={`${SIDEBAR_ROW_CLASS} w-full text-ink-muted transition-colors hover:bg-ink/[0.04] hover:text-ink`}
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
        {!isCollapsed && <BuildStamp className="mt-2 px-2" />}
      </div>
    </NavDrawer>
  );
}

const NONE_CLOSED: ReadonlySet<string> = new Set();

type RenderItem = (item: NavItem, to?: string) => ReactNode;

/**
 * The full sidebar: the primary entries, then each headed group, then the footer. A headed
 * group opens and closes from its heading; the one holding the current page is always open,
 * so the highlight can never be folded away.
 */
function GroupedNav({
  groups,
  current,
  closed,
  onToggle,
  isCollapsed,
  renderItem,
  collapsible = true,
}: {
  groups: NavGroup[];
  current: NavItem | undefined;
  closed: ReadonlySet<string>;
  onToggle?: (heading: string) => void;
  isCollapsed: boolean;
  renderItem: RenderItem;
  collapsible?: boolean;
}) {
  const baseId = useId();
  return (
    <>
      {groups.map((group, index) => {
        const { heading } = group;
        if (group.footer) {
          return (
            <div key={`footer-${index}`} className="mt-2 border-t border-line pt-3">
              {group.items.map((item) => renderItem(item))}
            </div>
          );
        }
        const holdsCurrent = group.items.some((item) => item.href === current?.href);
        const open = heading === null || holdsCurrent || !closed.has(heading);
        const bodyId = `${baseId}-group-${index}`;
        return (
          <div
            key={heading ?? `main-${index}`}
            className="mb-4"
            role={heading ? "group" : undefined}
            aria-label={heading ?? undefined}
          >
            {heading && (
              <SidebarGroupHeading
                isCollapsed={isCollapsed}
                toggle={
                  collapsible && onToggle && !holdsCurrent
                    ? { open, onToggle: () => onToggle(heading), controls: bodyId }
                    : undefined
                }
              >
                {heading}
              </SidebarGroupHeading>
            )}
            <SidebarGroupBody id={bodyId} open={open}>
              {group.items.map((item) => renderItem(item))}
            </SidebarGroupBody>
          </div>
        );
      })}
    </>
  );
}

/**
 * The trial sidebar: the six entries a new owner needs before their first test call, then
 * "Show everything", which opens every other screen in place, grouped as the full sidebar
 * groups them. Opened with no toggle when the page shown is one of those others.
 */
function TrialNav({
  slug,
  groups,
  current,
  agentsTo,
  everything,
  isCollapsed,
  renderItem,
}: {
  slug: string;
  groups: NavGroup[];
  current: NavItem | undefined;
  /** Where "Your agent" leads while the first run is due; the roster otherwise. */
  agentsTo: string | undefined;
  everything: { on: boolean; set: (on: boolean) => void };
  isCollapsed: boolean;
  renderItem: RenderItem;
}) {
  const restId = useId();
  const items = trialNavigation(groups, slug);
  const shown = new Set(items.map((item) => item.href));
  const billing = `/c/${slug}/billing`;
  const agents = `/c/${slug}/agents`;
  const rest = groups
    .map((group) => ({ ...group, items: group.items.filter((item) => !shown.has(item.href)) }))
    .filter((group) => group.items.length > 0);
  const forced = current !== undefined && !shown.has(current.href);
  const open = everything.on || forced;
  const draw = (item: NavItem) => renderItem(item, item.href === agents ? (agentsTo ?? item.href) : item.href);
  return (
    <>
      <div className="mb-2">{items.filter((item) => item.href !== billing).map(draw)}</div>
      <div className="mb-2 border-t border-line pt-2">
        {items.filter((item) => item.href === billing).map(draw)}
        {!forced && (
          <button
            type="button"
            aria-expanded={open}
            aria-controls={restId}
            onClick={() => everything.set(!open)}
            title={isCollapsed ? (open ? "Show less" : "Show everything") : undefined}
            className={`${SIDEBAR_ROW_CLASS} w-full text-ink-muted transition-colors hover:bg-ink/[0.04] hover:text-ink`}
          >
            <ChevronDown
              aria-hidden
              className={`h-4 w-4 shrink-0 text-ink-faint motion-safe:transition-transform motion-safe:duration-200 ${
                open ? "rotate-180" : ""
              }`}
            />
            <SidebarLabel isCollapsed={isCollapsed}>{open ? "Show less" : "Show everything"}</SidebarLabel>
          </button>
        )}
      </div>
      <SidebarGroupBody id={restId} open={open}>
        <div className="pt-2">
          <GroupedNav
            groups={rest}
            current={current}
            closed={NONE_CLOSED}
            isCollapsed={isCollapsed}
            renderItem={renderItem}
            collapsible={false}
          />
        </div>
      </SidebarGroupBody>
    </>
  );
}

/** Per browser: whether the trial sidebar's "Show everything" was left open. */
const SHOW_EVERYTHING_KEY = "calevate:sidebar-show-everything";

/**
 * Read after mount rather than during render, so the server's HTML and the first client
 * render agree; the trial view itself waits on `GET /v1/trial`, so nothing visibly jumps.
 */
function useShowEverything(): { on: boolean; set: (on: boolean) => void } {
  const [on, setOn] = useState(false);
  useEffect(() => {
    try {
      setOn(window.localStorage.getItem(SHOW_EVERYTHING_KEY) === "1");
    } catch {
      // Storage blocked: the list starts short, and the button still opens it.
    }
  }, []);
  const set = useCallback((next: boolean) => {
    setOn(next);
    try {
      window.localStorage.setItem(SHOW_EVERYTHING_KEY, next ? "1" : "0");
    } catch {
      // Not remembered in this browser; the choice still holds for this visit.
    }
  }, []);
  return { on, set };
}
