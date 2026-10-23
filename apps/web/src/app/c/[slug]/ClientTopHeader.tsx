"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu } from "lucide-react";

import { NotificationCenter, type NotificationItem } from "@/components/arc/notification-center";
import { ClientCopilotDock } from "@/components/copilot/CopilotDock";
import { LiveCallsPill } from "@/components/console/liveCalls";
import { BAR_STATUS } from "@/components/console/statusPill";
import { NOTICE_DOT, SHELL_RAIL_CLASS, formatCount, formatCountOf } from "@/components/ui";
import { useAttention, type AttentionKind } from "@/lib/api/attention";
import { useClientRealm } from "@/lib/api/session";
import { creditLeftPhrase, useWallet, walletState } from "@/lib/api/wallet";
import { clientNavigation } from "@/lib/clientNav";
import { useDesktopAlerts } from "@/lib/desktopAlerts";

import { currentItem } from "./ClientSidebar";
import { TrialChip, trialView } from "./TrialBanner";

/** Rows the bell shows; the attention screen has the rest. */
const BELL_ROWS = 6;

/** Failures read red, things slowing down read amber, good news (a hot lead) stays neutral. */
const KIND_TONE: Record<AttentionKind, NotificationItem["tone"]> = {
  lead_blocked: "warn",
  delivery_failed: "danger",
  campaign_stalled: "warn",
  kb_rejected: "warn",
  inbound_stopped: "danger",
  action_broken: "danger",
  lead_hot: "default",
  call_failed: "danger",
  credit_low: "warn",
  forwarded_line_quiet: "warn",
};

export function ClientTopHeader({ slug, onMenuToggle }: { slug: string; onMenuToggle: () => void }) {
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
  // New items on the bell also become desktop notifications, once turned on in Alerts.
  useDesktopAlerts(slug, attention.data, href);

  return (
    // The header spans the window (its border and background are the shell's, not the
    // page's) while its CONTENTS ride the same rail as the content below — see
    // `SHELL_RAIL_CLASS`. Padding is unchanged and was never the defect.
    <header className="sticky top-0 z-header flex h-[72px] shrink-0 items-center border-b border-line bg-surface px-4 lg:px-8">
      <div className={`${SHELL_RAIL_CLASS} flex items-center justify-between gap-3`}>
        <div className="flex min-w-0 items-center gap-2 sm:gap-3">
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

        <div className="flex shrink-0 items-center gap-1 sm:gap-2 lg:gap-3">
          {/* Calls in progress now, from the existing 20-second call poll. Renders
              nothing unless at least one call is live. */}
          <LiveCallsPill slug={slug} />
          {/* While a trial runs (or a test-calls trial has run out unpaid) the trial chip
              stands in for the credit chip: the trial is what the balance means then. */}
          <TrialChip slug={slug} />
          <CreditChip slug={slug} />
          <NotificationCenter
            heading="Needs attention"
            label={
              attention.error != null
                ? "Needs attention: we couldn't check for new items. Open to try again."
                : waiting !== undefined && waiting > 0
                  ? `Needs attention: ${formatCountOf(waiting, "item")}`
                  : "Needs attention"
            }
            title={
              attention.error != null
                ? "We couldn't check for new items. Open to try again."
                : undefined
            }
            state={attention.error != null ? "error" : attention.data ? "ready" : "loading"}
            count={waiting}
            onRetry={() => void attention.refetch()}
            items={(attention.data?.items ?? []).slice(0, BELL_ROWS).map((item) => ({
              id: `${item.kind}-${item.id}-${item.occurred_at}`,
              title: item.title,
              detail: item.detail,
              at: item.occurred_at,
              href: item.href ? href(`/c/${slug}${item.href}`) : null,
              tone: KIND_TONE[item.kind],
            }))}
            shortfall={
              waiting !== undefined && waiting > BELL_ROWS
                ? `The newest ${formatCount(BELL_ROWS)} of ${formatCount(waiting)}.`
                : undefined
            }
            seeAll={{ href: href(`/c/${slug}/attention`), label: "Open everything that needs you" }}
          />
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
