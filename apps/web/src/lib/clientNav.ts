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
 *  - one `heading:` per group, `null` for the primary one.
 *
 * A screen added, renamed or removed here and not in `screens.py` turns that test red —
 * which is the whole point: the defect that produced it was an assistant telling a client,
 * on the billing screen, that there was no billing screen.
 */

import type { ComponentType } from "react";

import {
  Activity,
  BarChart3,
  BellRing,
  Blocks,
  BookLock,
  BookOpen,
  Bot,
  BrainCircuit,
  Coins,
  FileSignature,
  FileText,
  GitMerge,
  LayoutDashboard,
  Megaphone,
  MessageSquare,
  PhoneCall,
  PhoneForwarded,
  PhoneOff,
  ReceiptIndianRupee,
  ScrollText,
  ShieldCheck,
  Sparkles,
  Target,
  UserCog,
  Users,
  Wallet,
} from "lucide-react";

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
}

export interface NavGroup {
  /** Null for the primary group, which carries no heading. */
  heading: string | null;
  items: NavItem[];
}

export function clientNavigation(slug: string): NavGroup[] {
  return [
    {
      heading: null,
      items: [
        { href: `/c/${slug}`, label: "Dashboard", icon: LayoutDashboard },
        // Directly under Dashboard because it is the daily triage queue — the one list
        // with a time cost attached to ignoring it. It used to sit in a secondary
        // "Operations" group beside Campaign review, a screen most accounts see once,
        // while the header bell promoted it — the sidebar now agrees with the bell
        // (ux-audit client-daily-work C2).
        { href: `/c/${slug}/attention`, label: "Needs attention", icon: Target },
        { href: `/c/${slug}/campaigns`, label: "Campaigns", icon: Megaphone },
        { href: `/c/${slug}/agents`, label: "Agents", icon: Bot },
        { href: `/c/${slug}/calls`, label: "Call logs", icon: PhoneCall },
        { href: `/c/${slug}/leads`, label: "Leads", icon: Users },
        // Beside Leads rather than under "Compliance & data": a promised call-back is
        // work waiting to happen, checked daily by whoever watches the leads, not a
        // record consulted when something goes wrong.
        { href: `/c/${slug}/callbacks`, label: "Call-backs", icon: PhoneForwarded },
        { href: `/c/${slug}/knowledge`, label: "Knowledge base", icon: BookOpen },
        { href: `/c/${slug}/performance`, label: "Performance", icon: BarChart3 },
      ],
    },
    {
      // Weekly-or-rarer reads, grouped by cadence rather than left at daily weight:
      // Quality is a weekly review and Campaign review is a once-per-campaign gate.
      heading: "Reports & reviews",
      items: [
        { href: `/c/${slug}/quality`, label: "Quality", icon: ShieldCheck },
        { href: `/c/${slug}/campaign-review`, label: "Campaign review", icon: FileText },
      ],
    },
    {
      heading: "Compliance & data",
      items: [
        // FIRST IN THIS GROUP because it gates the rest of it: until the owner has
        // accepted, `agreements_blocker` refuses every dial and every publish, so a
        // client working down this list would meet the refusal at the bottom instead of
        // the door at the top. It is also the one screen that names the operational
        // blockers (KYC, PE registration, DND scrub, first-campaign hold) somewhere other
        // than a failed campaign launch.
        { href: `/c/${slug}/agreements`, label: "Agreements", icon: FileSignature },
        // Second because it is the other DOOR: the identity check that legally gates
        // outbound dialling. It sat under "Settings & account" — the group of things set
        // once and forgotten — which is exactly where a client whose calling is blocked
        // would not look (ux-audit C-3 🔒).
        { href: `/c/${slug}/verification`, label: "Verification", icon: ShieldCheck },
        { href: `/c/${slug}/do-not-call`, label: "Do not call", icon: PhoneOff },
        { href: `/c/${slug}/messaging-consent`, label: "Messaging consent", icon: MessageSquare },
        { href: `/c/${slug}/lead-sources`, label: "Lead sources", icon: GitMerge },
        { href: `/c/${slug}/data-rights`, label: "Data rights", icon: ScrollText },
        { href: `/c/${slug}/caller-notice`, label: "Your privacy notice", icon: BookLock },
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
        // Which AI model every agent thinks with, and what each one costs a minute. It
        // sits in this group rather than beside "Agents" because it is an ACCOUNT-wide
        // default that happens to be about agents — the same reason the spending limit
        // lives under Usage rather than on each campaign. One agent can still be put on
        // its own model, and that control is on the agent.
        { href: `/c/${slug}/settings/models`, label: "AI model", icon: BrainCircuit },
        { href: `/c/${slug}/integrations`, label: "Integrations", icon: Blocks },
        // CALLING CREDIT — the wallet, its history, and the one place a client buys more.
        // It sits beside Usage rather than inside it because it answers a different
        // question: Usage is "what has this month cost", this is "how much is left, how
        // long does it last, and how do I add more". It is also the ONE screen in this
        // group that `staff` can read (`wallet:read`), because the thing that stops a
        // staff member dialling is an empty wallet.
        //
        // AHEAD OF Usage, and that ordering changed with the billing motion. It sat
        // seventh in this group while every account was invoiced and the wallet was a
        // screen almost nobody had a reason to open. Prepaid is now what an account gets
        // unless an operator deliberately puts it on a retainer, which makes this the
        // screen a client comes looking for when their campaigns have stopped — and the
        // one they must be able to find from a phone, in a hurry, without reading nine
        // labels first.
        { href: `/c/${slug}/credits`, label: "Calling credit", icon: Wallet },
        { href: `/c/${slug}/usage`, label: "Usage", icon: Activity },
        // WHERE the Usage number came from, one screen over. Usage answers "how much and
        // how much is left"; this answers "which agent and which call", which is the
        // question an owner asks the moment the first one has a figure in it. Its own
        // entry rather than a panel on Usage because it is a per-call table that grows
        // with the month, and because a client following up on a bill is looking for the
        // word "Spend" rather than scrolling a summary screen.
        { href: `/c/${slug}/spend`, label: "Spend", icon: Coins },
        // What the console's AI help has used against the allowance the plan includes,
        // and the one place a person can agree to spend money on more (D-127 G-5). It
        // sits beside Usage rather than inside it because it is a different wallet
        // question: Usage is what the CLIENT is billed for, this is what CALEVATE
        // absorbs until a ceiling.
        { href: `/c/${slug}/ai-assist`, label: "AI help", icon: Sparkles },
        { href: `/c/${slug}/invoice`, label: "Invoice", icon: ReceiptIndianRupee },
      ],
    },
  ];
}

