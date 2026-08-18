"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { use, useState, type ComponentType } from "react";
import {
  Activity,
  BarChart3,
  Bell,
  BellRing,
  Blocks,
  Bot,
  BookOpen,
  FileText,
  GitMerge,
  LayoutDashboard,
  Megaphone,
  Menu,
  MessageSquare,
  Mic,
  PanelLeftClose,
  PanelLeftOpen,
  PhoneCall,
  PhoneOff,
  ReceiptIndianRupee,
  ScrollText,
  ShieldCheck,
  Sparkles,
  UserCog,
  Target,
  Users,
  X,
} from "lucide-react";

import { Providers } from "@/app/providers";
import { NavDrawer } from "@/components/navDrawer";
import { Avatar, MAIN_CONTENT_ID, ProblemNotice, Skeleton, SkipLink } from "@/components/ui";
import { useAttention } from "@/lib/api/attention";
import { useMe } from "@/lib/api/hooks";
import { ClientRealmProvider, useClientRealm } from "@/lib/api/session";
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

function navigation(slug: string): NavGroup[] {
  return [
    {
      heading: null,
      items: [
        { href: `/c/${slug}`, label: "Dashboard", icon: LayoutDashboard },
        { href: `/c/${slug}/campaigns`, label: "Campaigns", icon: Megaphone },
        { href: `/c/${slug}/agents`, label: "Voice agents", icon: Bot },
        { href: `/c/${slug}/calls`, label: "Call logs", icon: PhoneCall },
        { href: `/c/${slug}/leads`, label: "Leads", icon: Users },
        { href: `/c/${slug}/knowledge`, label: "Knowledge base", icon: BookOpen },
        { href: `/c/${slug}/performance`, label: "Performance", icon: BarChart3 },
        { href: `/c/${slug}/quality`, label: "Quality", icon: ShieldCheck },
      ],
    },
    {
      heading: "Operations",
      items: [
        { href: `/c/${slug}/attention`, label: "Needs attention", icon: Target },
        { href: `/c/${slug}/campaign-review`, label: "Campaign review", icon: FileText },
      ],
    },
    {
      heading: "Compliance & data",
      items: [
        { href: `/c/${slug}/do-not-call`, label: "Do not call", icon: PhoneOff },
        { href: `/c/${slug}/messaging-consent`, label: "Messaging consent", icon: MessageSquare },
        { href: `/c/${slug}/lead-sources`, label: "Lead sources", icon: GitMerge },
        { href: `/c/${slug}/data-rights`, label: "Data rights", icon: ScrollText },
      ],
    },
    {
      heading: "Settings & account",
      items: [
        { href: `/c/${slug}/settings/team`, label: "Team", icon: UserCog },
        // The one screen where the owner can agree to be messaged about their own
        // account. It sits here rather than under "Compliance & data" on purpose: that
        // group is about the client's obligations to their CUSTOMERS, and this is a
        // setting about what we send to THEM.
        { href: `/c/${slug}/settings/alerts`, label: "Alerts", icon: BellRing },
        { href: `/c/${slug}/integrations`, label: "Integrations", icon: Blocks },
        { href: `/c/${slug}/usage`, label: "Usage", icon: Activity },
        // What the console's AI help has used against the allowance the plan includes,
        // and the one place a person can agree to spend money on more (D-127 G-5). It
        // sits beside Usage rather than inside it because it is a different wallet
        // question: Usage is what the CLIENT is billed for, this is what CALEVATE
        // absorbs until a ceiling.
        { href: `/c/${slug}/ai-assist`, label: "AI help", icon: Sparkles },
        { href: `/c/${slug}/invoice`, label: "Invoice", icon: ReceiptIndianRupee },
        { href: `/c/${slug}/verification`, label: "Verification", icon: ShieldCheck },
      ],
    },
  ];
}

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
  const groups = navigation(slug);
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
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand text-white">
            <Mic className="h-5 w-5" />
          </span>
          {!isCollapsed && (
            <span className="whitespace-nowrap">
              <span className="block text-[17px] font-bold leading-none tracking-tight text-ink">
                Calevate
              </span>
              <span className="block text-[11px] font-medium text-ink-muted">AI voice agents</span>
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
      </div>
    </NavDrawer>
  );
}

function TopHeader({ slug, onMenuToggle }: { slug: string; onMenuToggle: () => void }) {
  const pathname = usePathname();
  const { session, href } = useClientRealm();
  const attention = useAttention(session);
  const title = currentItem(navigation(slug), pathname)?.label ?? "Dashboard";

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
      <div className="bg-amber-500 px-4 py-1.5 text-center text-xs font-semibold text-amber-950">
        Viewing as {me.data.organization?.name ?? slug} — read only. Every page view is
        logged, and anything that would change this account is refused.
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
        </ClientRealmProvider>
      </div>
    </Providers>
  );
}
