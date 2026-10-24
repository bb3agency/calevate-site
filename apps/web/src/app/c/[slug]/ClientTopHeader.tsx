"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useRef } from "react";
import { Menu } from "lucide-react";

import { useActionFeedback } from "@/components/arc/feedback";
import { NotificationCenter, type NotificationItem } from "@/components/arc/notification-center";
import { ClientCopilotDock } from "@/components/copilot/CopilotDock";
import { LiveCallsPill } from "@/components/console/liveCalls";
import { BAR_STATUS } from "@/components/console/statusPill";
import { NOTICE_DOT, SHELL_RAIL_CLASS, formatCount, formatCountOf } from "@/components/ui";
import { useAttention } from "@/lib/api/attention";
import { useWriteAccess } from "@/lib/api/hooks";
import {
  useMarkNotificationsSeen,
  useNotifications,
  type Notification,
} from "@/lib/api/notifications";
import { useClientRealm } from "@/lib/api/session";
import { creditLeftPhrase, useWallet, walletState } from "@/lib/api/wallet";
import { clientNavigation } from "@/lib/clientNav";
import { useDesktopAlerts } from "@/lib/desktopAlerts";

import { consoleHref } from "./ClientAnnouncements";
import { currentItem } from "./ClientSidebar";
import { TrialChip, trialView } from "./TrialBanner";

/** Failures read red, things slowing down read amber, news and good news stay neutral. */
const TONE: Record<Notification["tone"], NotificationItem["tone"]> = {
  info: "default",
  success: "default",
  warning: "warn",
  critical: "danger",
};

export function ClientTopHeader({ slug, onMenuToggle }: { slug: string; onMenuToggle: () => void }) {
  const pathname = usePathname();
  const { session, href } = useClientRealm();
  const attention = useAttention(session);
  const title = currentItem(clientNavigation(slug), pathname)?.label ?? "Dashboard";

  // New attention items also become desktop notifications, once turned on in Alerts.
  useDesktopAlerts(slug, attention.data, href);

  return (
    // The header spans the window (its border and background are the shell's, not the
    // page's) while its CONTENTS ride the same rail as the content below — see
    // `SHELL_RAIL_CLASS`. Padding is unchanged and was never the defect.
    <header className="sticky top-0 z-header flex h-[72px] shrink-0 items-center border-b border-line bg-surface px-3 sm:px-4 lg:px-8">
      <div className={`${SHELL_RAIL_CLASS} flex items-center justify-between gap-2 sm:gap-3`}>
        <div className="flex min-w-0 items-center gap-1.5 sm:gap-3">
          <button
            type="button"
            onClick={onMenuToggle}
            aria-label="Open navigation"
            className="press flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-ink-muted hover:bg-ink/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 touch:h-11 touch:w-11 lg:hidden dark:hover:bg-white/5"
          >
            <Menu className="h-5 w-5" />
          </button>
          {/* A step down on a phone, where the menu button and two header buttons leave about
              190px: at the title size "Your phone numbers" was cut to "Your phone numb…". */}
          <h1 className="truncate text-heading text-ink sm:text-title">{title}</h1>
        </div>

        <div className="flex shrink-0 items-center gap-0.5 sm:gap-2 lg:gap-3">
          {/* Calls in progress now, from the existing 20-second call poll. Renders
              nothing unless at least one call is live. */}
          <LiveCallsPill slug={slug} />
          {/* While a trial runs (or a test-calls trial has run out unpaid) the trial chip
              stands in for the credit chip: the trial is what the balance means then. */}
          <TrialChip slug={slug} />
          <CreditChip slug={slug} />
          <NotificationBell slug={slug} />
          {/* The screen assistant, in the bar rather than floating over the page: a floating
              button sat on top of whatever filled the bottom-right corner. Inside
              \`ClientRealmProvider\` (it reads the realm session, view-as included); its panel opens
              under this bar. */}
          <ClientCopilotDock placement="header" />
        </div>
      </div>
    </header>
  );
}

/**
 * The bell: the account's one feed of what needs attention and what we announced, newest
 * first (`/v1/notifications`), with this person's unread count as the badge.
 *
 * Closing it records what was shown as seen. A failed mark costs nothing but the badge staying up, so it is not
 * raised as an error; a failed READ is said on the bell (warn dot, words in its name),
 * never drawn as an all-clear.
 */
function NotificationBell({ slug }: { slug: string }) {
  const { session, href } = useClientRealm();
  const feed = useNotifications(session, BELL_ROWS);
  const markSeen = useMarkNotificationsSeen(session);
  const markFeedback = useActionFeedback(markSeen, { errorDisplay: "inline" });
  // Recording "seen" is a write (`leads:write`); a session without it, such as an operator
  // viewing the account, only reads the bell.
  const mayMark = useWriteAccess(session, "leads:write", "mark notifications read").allowed;
  const data = feed.data;
  const unread = data?.unread;
  const attentionShown = data?.items.filter((item) => item.source === "attention").length ?? 0;
  const newest = data?.items[0]?.occurred_at;
  // Marked on CLOSE, through the newest item that was on screen when it opened: the rows
  // keep their "new" look while they are being read, and anything that arrived meanwhile
  // stays unread.
  const shownThrough = useRef<string | undefined>(undefined);

  return (
    <NotificationCenter
      heading="Notifications"
      label={
        feed.error != null
          ? "Notifications: we couldn't check for new items. Open to try again."
          : unread !== undefined && unread > 0
            ? `Notifications: ${formatCount(unread)} unread`
            : "Notifications"
      }
      title={feed.error != null ? "We couldn't check for new items. Open to try again." : undefined}
      state={feed.error != null && !data ? "error" : data ? "ready" : "loading"}
      partial={feed.error != null && data !== undefined}
      count={unread}
      onRetry={() => void feed.refetch()}
      onOpenChange={(open) => {
        if (open) {
          shownThrough.current = unread !== undefined && unread > 0 ? newest : undefined;
          return;
        }
        if (shownThrough.current && mayMark) markFeedback.run(shownThrough.current);
        shownThrough.current = undefined;
      }}
      emptyText="Nothing new. We will put anything that needs you here."
      items={(data?.items ?? []).map((item) => ({
        id: `${item.source}-${item.id}`,
        title: item.title,
        detail: item.detail ?? undefined,
        at: item.occurred_at,
        href: item.href ? consoleHref(item.href, slug, href) : null,
        tone: TONE[item.tone],
        unread: item.unread,
      }))}
      shortfall={
        data && data.attention_total > attentionShown
          ? `${formatCountOf(data.attention_total, "thing")} need${data.attention_total === 1 ? "s" : ""} attention in all.`
          : undefined
      }
      seeAll={{ href: href(`/c/${slug}/attention`), label: "Open everything that needs you" }}
    />
  );
}

/** Rows the bell asks for; the attention screen has the rest. */
const BELL_ROWS = 20;

/**
 * Credit in the bar, ONLY when it is about to stop calls or already has. A healthy balance
 * is on the dashboard and the billing screen; showing it on every screen would be one more
 * thing in the bar that is usually not news (feedback-patterns: signal when it is
 * actionable). Words carry the state, the warn colour only repeats them.
 */
function CreditChip({ slug }: { slug: string }) {
  const { session, href } = useClientRealm();
  const wallet = useWallet(session);
  if (!wallet.data) return null;
  if (trialView(wallet.data) !== null) return null;
  const state = walletState(wallet.data);
  if (state !== "low" && state !== "stopped") return null;
  const text = state === "stopped" ? "Calls stopped" : creditLeftPhrase(wallet.data);
  return (
    <Link
      href={href(`/c/${slug}/billing?tab=credits`)}
      className={`${BAR_STATUS} hidden text-ink sm:inline-flex`}
    >
      <span aria-hidden className={`h-2 w-2 shrink-0 rounded-full ${NOTICE_DOT[state === "stopped" ? "stop" : "warn"]}`} />
      {text}
      <span className="text-brand-strong">Add credit</span>
    </Link>
  );
}
