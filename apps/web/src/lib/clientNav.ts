/**
 * THE CLIENT CONSOLE'S NAVIGATION — the one list of what a client can reach and what it
 * is CALLED, and the source of truth for both readers of that fact.
 *
 * It lived inside `app/c/[slug]/layout.tsx` until the copilot needed it. The layout is
 * still the only thing that RENDERS it — the sidebar and the page title read it through
 * `currentNavItem`, exactly as before — but it is no longer the only thing that has to
 * agree with it: `apps/api/copilot/screens.py` carries the same screens so the assistant
 * can tell a client where a thing lives, and `apps/api/copilot/screens_test.py` parses
 * THIS file and fails when the two disagree.
 *
 * So this module is a parse target as well as a value, and that is why it is a small file
 * of plain literals rather than a section of a 500-line shell. Two properties that test
 * depends on, both cheap to keep:
 *
 *  - one entry per line, in the form `{ href: `/c/${slug}/x`, label: "Y", icon: Z },`
 *  - one `heading:` per group, `null` for a group with no heading (the primary one and the
 *    footer).
 *
 * A screen added, renamed or removed here and not in `screens.py` turns that test red —
 * which is the whole point: the defect that produced it was an assistant telling a client,
 * on the billing screen, that there was no billing screen.
 */

import type { ComponentType } from "react";

import {
  BadgeCheck,
  BarChart3,
  BellRing,
  Blocks,
  BookLock,
  BookOpen,
  Bot,
  BrainCircuit,
  ClipboardList,
  FileSignature,
  GitMerge,
  LayoutDashboard,
  LifeBuoy,
  Megaphone,
  MessageSquare,
  Phone,
  PhoneCall,
  PhoneForwarded,
  PhoneIncoming,
  PhoneOutgoing,
  PhoneOff,
  ScrollText,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Store,
  Target,
  TrendingUp,
  UserCog,
  Users,
  Wallet,
  Workflow,
} from "lucide-react";

import { PipIcon } from "@/components/illustration/pip";
import type { LeadNouns } from "@/lib/businessCapabilities";
import { lookup } from "@/lib/lookup";

export interface NavItem {
  href: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  /**
   * A count the sidebar renders beside the label, or `undefined` for no badge.
   *
   * `navigation()` is a pure function of the slug and cannot read a query, so a badge is
   * INJECTED by the component that has the data — see `Sidebar`. That keeps the nav
   * structure a value the a11y sweep and `currentNavItem` can walk without a provider.
   *
   * `undefined` and never `?? 0`, for the bell's reason in `TopHeader`: a coalesce makes
   * a failed read indistinguishable from an all-clear, which is the "nobody is waiting"
   * claim §52 exists to stop the shell making.
   */
  badge?: number;
  /**
   * How urgent the count is: `stop` (red) for something that blocks the account, as an
   * unsigned agreement does; `warn` (amber) for work waiting on a person. Red on every
   * badge would make a routine queue read like a blocked account.
   */
  badgeTone?: "warn" | "stop";
}

export interface NavGroup {
  /** Null for a group that carries no heading: the primary one, and the footer. */
  heading: string | null;
  /**
   * Drawn at the foot of the list under a hairline rather than in reading order. Pip is the
   * one entry there: it answers questions about every screen above it, so it belongs to
   * none of their groups.
   */
  footer?: boolean;
  items: NavItem[];
}

/**
 * The groups follow what an owner is doing when they open the sidebar: setting agents to
 * work (Calling), reading what came of it (Results), teaching them (Knowledge), the legal
 * duties (Rules & records) and the account itself (Account). About seven entries a group,
 * so each reads at a glance (docs/design/redesign-2026-11-28/PLAN.md §4).
 */
export function clientNavigation(slug: string): NavGroup[] {
  return [
    {
      heading: null,
      items: [
        { href: `/c/${slug}`, label: "Dashboard", icon: LayoutDashboard },
        // Directly under Dashboard because it is the daily triage queue, the one list with a
        // time cost attached to ignoring it; the header bell promotes the same queue.
        { href: `/c/${slug}/attention`, label: "Needs attention", icon: Target },
        // D-1044: beside Needs attention, its other half: that queue is what is broken or
        // blocked; this is what would make results better, across the account.
        { href: `/c/${slug}/improve`, label: "Improve", icon: TrendingUp },
      ],
    },
    {
      heading: "Calling",
      items: [
        { href: `/c/${slug}/agents`, label: "Agents", icon: Bot },
        { href: `/c/${slug}/campaigns`, label: "Campaigns", icon: Megaphone },
        // D-997: what each of the business's numbers says when called, in one agent's voice.
        // "Inbound" stays the word (founder, 16 Nov and 28 Nov 2026).
        { href: `/c/${slug}/inbound`, label: "Inbound", icon: PhoneIncoming },
        // One person, one call, now or at a time (founder, 5 Nov 2026): the one-person
        // counterpart of Campaigns. "Make a call" over "Dialer", a campaign word in this trade.
        { href: `/c/${slug}/make-a-call`, label: "Make a call", icon: PhoneForwarded },
        // Calevate's numbers and the client's existing one forwarded to them, as two
        // sections of one screen. The path keeps its old segment so existing links land.
        { href: `/c/${slug}/phone-number`, label: "Phone numbers", icon: Phone },
      ],
    },
    {
      heading: "Results",
      items: [
        { href: `/c/${slug}/calls`, label: "Call logs", icon: PhoneCall },
        { href: `/c/${slug}/leads`, label: "Leads", icon: Users },
        // D-940: the steps each lead goes through after it arrives or after a call.
        { href: `/c/${slug}/follow-ups`, label: "Follow-ups", icon: Workflow },
        // A promised call-back is work waiting to happen, checked daily by whoever watches
        // the leads, so it sits with them rather than with the records below.
        { href: `/c/${slug}/callbacks`, label: "Call-backs", icon: PhoneOutgoing },
        { href: `/c/${slug}/performance`, label: "Performance", icon: BarChart3 },
        { href: `/c/${slug}/quality`, label: "Quality", icon: ShieldCheck },
      ],
    },
    {
      heading: "Knowledge",
      items: [
        // D-874: named for what an owner asks ("what do my agents know?"), not for the
        // machinery. The path keeps its old segment so existing links still land.
        { href: `/c/${slug}/knowledge`, label: "What your agents know", icon: BookOpen },
      ],
    },
    {
      heading: "Rules & records",
      items: [
        // FIRST IN THIS GROUP because it gates the rest of it: until the owner has accepted,
        // `agreements_blocker` refuses every dial and every publish, so a client working down
        // this list meets the door at the top rather than the refusal at the bottom.
        { href: `/c/${slug}/agreements`, label: "Agreements", icon: FileSignature },
        // The other door: the identity check that legally gates outbound dialling (D-692)
        // and (D-875) what we hold; `/verification` redirects here.
        { href: `/c/${slug}/verify-business`, label: "Verify your business", icon: BadgeCheck },
        { href: `/c/${slug}/do-not-call`, label: "Do not call", icon: PhoneOff },
        { href: `/c/${slug}/messaging-consent`, label: "Messaging consent", icon: MessageSquare },
        // One screen per client (D-716): how new leads are called, the after-hours queue
        // and the sources they come from.
        { href: `/c/${slug}/lead-sources`, label: "Leads & hours", icon: GitMerge },
        { href: `/c/${slug}/data-rights`, label: "Data rights", icon: ScrollText },
        { href: `/c/${slug}/caller-notice`, label: "Your privacy notice", icon: BookLock },
        // D-943: what to do, in order, if customers' data leaks.
        { href: `/c/${slug}/breach-playbook`, label: "If data leaks", icon: ShieldAlert },
      ],
    },
    {
      heading: "Account",
      items: [
        // The business's own facts, which every agent answers with (D-695): first because an
        // agent cannot take calls without them.
        { href: `/c/${slug}/settings/business`, label: "Business profile", icon: Store },
        // What every call writes down for a lead (founder decision 15): beside the profile
        // because a custom business's own details are drafted from it.
        { href: `/c/${slug}/settings/lead-details`, label: "Lead details", icon: ClipboardList },
        { href: `/c/${slug}/settings/team`, label: "Team", icon: UserCog },
        // What we send the OWNER, which is why it is here and not under Rules & records:
        // that group is about the client's obligations to their customers.
        { href: `/c/${slug}/settings/alerts`, label: "Alerts", icon: BellRing },
        // What happens to callers if an agent cannot take calls (D-701). Beside Alerts: both
        // are about what we do for the owner when something needs them.
        { href: `/c/${slug}/settings/line-protection`, label: "Line protection", icon: LifeBuoy },
        // The AI and recording notices every call opens with, one switch each for the whole
        // account (D-1021).
        { href: `/c/${slug}/settings/call-notices`, label: "Call notices", icon: Bot },
        // An ACCOUNT-wide default that happens to be about agents; one agent can still be put
        // on its own model, and that control is on the agent.
        { href: `/c/${slug}/settings/models`, label: "AI model", icon: BrainCircuit },
        { href: `/c/${slug}/integrations`, label: "Integrations", icon: Blocks },
        // ONE hub, four tabs (D-525); the four old routes redirect into the tab that answers
        // them. It reads on `wallet:read`, which staff hold, so a staff member still sees why
        // dialling stopped; the owner's figures are refused per tab inside the screen.
        { href: `/c/${slug}/billing`, label: "Credits & billing", icon: Wallet },
        // What Calevate absorbs until a ceiling, as against what the client is billed for.
        { href: `/c/${slug}/ai-assist`, label: "AI help", icon: Sparkles },
      ],
    },
    {
      heading: null,
      footer: true,
      items: [
        { href: `/c/${slug}/assistant`, label: "Pip", icon: PipIcon },
      ],
    },
  ];
}

/**
 * THE SHORT TRIAL SIDEBAR (founder, 28 Nov 2026): what a trial owner needs before their first
 * test call, in this order. Paths under `/c/<slug>`; `""` is the dashboard. The last one sits
 * under a hairline, apart from the daily ones.
 *
 * A FILTER over `clientNavigation()` rather than a second list, so this file stays the one
 * literal `screens_test.py` parses and Pip can still name every screen.
 */
export const TRIAL_NAV_PATHS = ["", "/agents", "/make-a-call", "/calls", "/assistant", "/billing"] as const;

/** What the trial sidebar calls the agents entry: a new owner has one agent, not a roster. */
export const TRIAL_AGENTS_LABEL = "Your agent";

/**
 * The trial sidebar's entries, in `TRIAL_NAV_PATHS` order, taken from `groups` so account
 * words and badges carry over. A path the navigation does not have is skipped, never made up.
 */
export function trialNavigation(groups: NavGroup[], slug: string): NavItem[] {
  const byHref = new Map(groups.flatMap((group) => group.items).map((item) => [item.href, item]));
  return TRIAL_NAV_PATHS.flatMap((path) => {
    const item = byHref.get(`/c/${slug}${path}`);
    if (!item) return [];
    return [path === "/agents" ? { ...item, label: TRIAL_AGENTS_LABEL } : item];
  });
}

/**
 * Does this account get the short sidebar? Only on a trial with no test minute used yet, and
 * only once `GET /v1/trial` has answered: while it loads, or after it fails, the full sidebar
 * shows, because hiding screens on a guess would hide them from an account that needs them.
 */
export function showsTrialNav(trial: { on_trial: boolean; minutes_used: number } | undefined): boolean {
  return trial !== undefined && trial.on_trial && trial.minutes_used === 0;
}

/** Labels an account whose agents all help customers reads (`useLeadNouns`), by path. */
const NAV_LABEL_FOR_CALLERS: Readonly<Record<string, keyof LeadNouns>> = {
  leads: "Leads",
  "settings/lead-details": "LeadDetails",
};

/**
 * The navigation in this account's words: the leads entries renamed with `nouns`, paths kept.
 * Applied by the readers that render a label (`ClientSidebar`, `clientPageTitle`), so the list
 * above stays the one literal `screens_test.py` parses.
 */
export function inAccountWords(groups: NavGroup[], slug: string, nouns: LeadNouns): NavGroup[] {
  const prefix = `/c/${slug}/`;
  return groups.map((group) => ({
    ...group,
    items: group.items.map((item) => {
      const key = item.href.startsWith(prefix) ? lookup(NAV_LABEL_FOR_CALLERS, item.href.slice(prefix.length)) : undefined;
      return key ? { ...item, label: nouns[key] } : item;
    }),
  }));
}
