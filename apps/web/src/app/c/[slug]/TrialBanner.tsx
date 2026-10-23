"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { AnnouncementBar } from "@/components/arc/announcement-bar";
import { Popover } from "@/components/arc/popover";
import { UsageMeter } from "@/components/arc/usage-meter";
import { BAR_STATUS } from "@/components/console/statusPill";
import { TrialMeter, trialShareLeft } from "@/components/illustration/trialMeter";
import { FIELD_LABEL, PRIMARY_BUTTON, formatCount, istDateStamp } from "@/components/ui";
import { useClientRealm } from "@/lib/api/session";
import { useTrialPanel } from "@/lib/api/trialCalls";
import {
  activeTrial,
  trialEndsAt,
  trialTimeLeft,
  useWallet,
  type Wallet,
  type WalletTrial,
} from "@/lib/api/wallet";

/**
 * The free trial in the shell: a chip in the top bar while it runs (D-536, D-697), and a
 * one-line strip above the bar ONLY when it needs acting on — the last day, under a tenth
 * of the free minutes, or a test-calls trial that ended unpaid.
 *
 * The full-width strip on every screen is gone: on a phone it took half the first screen
 * to say what the dashboard's trial card already said. Every figure still comes from
 * `GET /v1/billing/wallet` (the query the dashboard and billing screens share), plus the
 * trial panel read (`GET /v1/trial`) for today's test calls, asked only while the chip's
 * panel is open.
 */

/** What the shell knows about this account's trial. */
export type TrialView =
  | { kind: "running"; trial: WalletTrial; testCallsOnly: boolean; prepaid: boolean }
  /** A test-calls-only trial (D-697) that ended before the account paid. */
  | { kind: "ended" };

export function trialView(wallet: Wallet | undefined): TrialView | null {
  if (!wallet) return null;
  const trial = activeTrial(wallet);
  if (trial !== null) {
    return { kind: "running", trial, testCallsOnly: trial.test_calls_only, prepaid: wallet.prepaid };
  }
  // `test_calls_only` is only set while the account has not paid, so an inactive one is a
  // trial that ran out rather than one the first payment converted.
  return wallet.trial?.test_calls_only ? { kind: "ended" } : null;
}

/** Under a tenth of the free minutes: worth interrupting for. */
export function minutesRunningLow(trial: WalletTrial): boolean {
  const total = trial.free_minutes;
  const left = trial.minutes_left;
  if (total === null || total === undefined || total <= 0) return false;
  if (left === null || left === undefined) return false;
  return left < total * 0.1;
}

export type TrialUrgency =
  | { kind: "ended" }
  | { kind: "last-day"; endsToday: boolean }
  | { kind: "low-minutes"; minutesLeft: number };

/** The one thing worth a strip above the bar, or null on an ordinary trial day. */
export function trialUrgency(view: TrialView | null, now: Date = new Date()): TrialUrgency | null {
  if (view === null) return null;
  if (view.kind === "ended") return { kind: "ended" };
  if (trialTimeLeft(view.trial, now).lastDay) {
    return { kind: "last-day", endsToday: istDateStamp(new Date(view.trial.ends_at)) === istDateStamp(now) };
  }
  if (minutesRunningLow(view.trial)) return { kind: "low-minutes", minutesLeft: view.trial.minutes_left ?? 0 };
  return null;
}

function urgencyHeadline(urgency: TrialUrgency): string {
  switch (urgency.kind) {
    case "ended":
      return "Your free trial has ended.";
    case "last-day":
      // The last 24 hours can cross midnight in India, so "today" is said only when it is.
      return urgency.endsToday ? "Your trial ends today." : "Your trial ends tomorrow.";
    case "low-minutes":
      return `Only ${urgency.minutesLeft} free ${urgency.minutesLeft === 1 ? "minute" : "minutes"} left.`;
  }
}

/** Closing the strip hides it for the rest of this IST day, on this browser, for this account. */
export function trialStripClosedKey(slug: string, now: Date = new Date()): string {
  return `calevate:trial-strip-closed:${slug}:${istDateStamp(now)}`;
}

function readClosed(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function writeClosed(key: string): void {
  try {
    window.localStorage.setItem(key, "1");
  } catch {
    // Storage blocked (private window, site data off): the strip still closes for this visit.
  }
}

/** Mounted in the client shell above the top bar. */
export function TrialBanner() {
  const { session, href } = useClientRealm();
  const wallet = useWallet(session);
  return (
    <TrialStrip
      wallet={wallet.data}
      slug={session.orgSlug}
      creditsHref={href(`/c/${session.orgSlug}/billing?tab=credits`)}
    />
  );
}

/** The strip itself, separate from the read so its states can be tested against a clock. */
export function TrialStrip({
  wallet,
  slug,
  creditsHref,
  now,
}: {
  wallet: Wallet | undefined;
  slug: string;
  creditsHref: string;
  now?: Date;
}) {
  const view = trialView(wallet);
  const urgency = trialUrgency(view, now);
  const key = trialStripClosedKey(slug, now);
  const [closed, setClosed] = useState(false);
  // Read after mount: storage does not exist on the server, and the key moves at IST midnight.
  useEffect(() => setClosed(readClosed(key)), [key]);

  if (view === null || urgency === null || closed) return null;
  // An invoiced account on a trial has no wallet to top up; its calls go on the invoice.
  const asksForCredit = view.kind === "ended" || view.testCallsOnly || view.prepaid;
  const tail = asksForCredit
    ? "Add credit to keep your agents answering."
    : "After that, calls go on your monthly invoice.";

  return (
    <AnnouncementBar
      tone="warn"
      title={urgencyHeadline(urgency)}
      detail={tail}
      action={asksForCredit ? { href: creditsHref, label: "Add credit" } : undefined}
      dismissLabel="Close until tomorrow"
      onDismiss={() => {
        writeClosed(key);
        setClosed(true);
      }}
    />
  );
}

/** "4 days" / "5 hours", and the phone's "4d" / "5h". */
function timeLeftLabels(trial: WalletTrial, now?: Date): { long: string; short: string } {
  const left = trialTimeLeft(trial, now);
  const long = left.text.replace(/ left$/, "");
  const n = Number.parseInt(long, 10);
  return { long, short: `${Number.isNaN(n) ? "" : n}${left.lastDay ? "h" : "d"}` };
}

/** The chip in the top bar: the trial at a glance, with its details one tap away. */
export function TrialChip({ slug }: { slug: string }) {
  const { session, href } = useClientRealm();
  const wallet = useWallet(session);
  const view = trialView(wallet.data);
  const [open, setOpen] = useState(false);
  // Today's test calls live on the trial panel read; asked only once somebody looks.
  const panel = useTrialPanel(session, open && view?.kind === "running" && view.testCallsOnly);
  if (view === null) return null;
  return (
    <TrialChipView
      view={view}
      creditsHref={href(`/c/${slug}/billing?tab=credits`)}
      open={open}
      onOpenChange={setOpen}
      callsToday={
        panel.data?.on_trial
          ? { used: panel.data.calls_today, cap: panel.data.daily_cap }
          : panel.isPending && open
            ? "loading"
            : null
      }
    />
  );
}

export function TrialChipView({
  view,
  creditsHref,
  open,
  onOpenChange,
  callsToday,
  now,
}: {
  view: TrialView;
  creditsHref: string;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Today's test calls; "loading" while the read is out, null when it did not come back. */
  callsToday?: { used: number; cap: number } | "loading" | null;
  now?: Date;
}) {
  // An ended trial has one next step, so the bar item IS that step: one tap to credits,
  // not a panel to open first.
  if (view.kind === "ended") {
    return (
      <Link href={creditsHref} aria-label="Free trial ended. Add credit" className={`${BAR_STATUS} text-ink`}>
        <TrialMeter left={0} className="h-4 w-4" />
        <span>Trial ended</span>
        <span className="hidden text-brand-strong sm:inline">Add credit</span>
      </Link>
    );
  }
  const running = view;
  const labels = timeLeftLabels(running.trial, now);
  const minutes = running.trial.minutes_left;
  const long = ["Trial", labels.long, minutes === null || minutes === undefined ? null : `${minutes} min`]
    .filter(Boolean)
    .join(" · ");
  const asksForCredit = running.testCallsOnly || running.prepaid;
  const free = running.trial.free_minutes;
  const freeMinutes = free === null || free === undefined || free <= 0 ? null : free;
  const minutesLeft = Math.max(0, Math.min(freeMinutes ?? 0, running.trial.minutes_left ?? freeMinutes ?? 0));

  return (
    <Popover
      label="Your free trial"
      align="end"
      open={open}
      onOpenChange={onOpenChange}
      className="w-80 max-w-[calc(100vw-1rem)]"
      trigger={
        <button
          type="button"
          aria-label={`Free trial: ${long}. Show details`}
          className={`${BAR_STATUS} text-ink-muted hover:text-ink max-sm:px-1.5`}
        >
          <TrialMeter left={trialShareLeft(running.trial)} className="h-4 w-4" />
          <span className="sm:hidden">
            <span className="sr-only">Trial · </span>
            {labels.short}
          </span>
          <span className="hidden sm:inline">{long}</span>
        </button>
      }
    >
      <div className="space-y-3 text-sm">
        <p className="font-semibold text-ink">Your free trial</p>
        <dl className="space-y-2">
          <div className="flex items-baseline justify-between gap-3">
            <dt className={FIELD_LABEL}>Ends</dt>
            <dd className="text-right text-ink">{trialEndsAt(running.trial)}</dd>
          </div>
          {running.testCallsOnly && callsToday === "loading" && (
            <div className="flex items-baseline justify-between gap-3">
              <dt className={FIELD_LABEL}>Test calls today</dt>
              <dd className="text-right text-ink">Checking…</dd>
            </div>
          )}
        </dl>
        {freeMinutes !== null ? (
          <UsageMeter
            label="Free minutes"
            used={freeMinutes - minutesLeft}
            limit={freeMinutes}
            usedText={formatCount(freeMinutes - minutesLeft)}
            caption={`${formatCount(minutesLeft)} of ${formatCount(freeMinutes)} left`}
            hint={minutesLeft <= 0 ? "Your free minutes are used up." : undefined}
          />
        ) : null}
        {running.testCallsOnly && callsToday !== null && callsToday !== undefined && callsToday !== "loading" ? (
          <UsageMeter
            label="Test calls today"
            used={callsToday.used}
            limit={callsToday.cap}
            usedText={formatCount(callsToday.used)}
            limitText={formatCount(callsToday.cap)}
            hint={callsToday.used >= callsToday.cap ? "That is today's limit. More open tomorrow." : undefined}
          />
        ) : null}
        <p className="text-ink-muted">
          {!running.testCallsOnly
            ? "Calls are on us until then: nothing is taken from your calling credit, and an empty balance does not stop your agents."
            : "Answering calls, campaigns, your own number and business verification open once you add credit."}
        </p>
        {asksForCredit && (
          <Link href={creditsHref} className={`${PRIMARY_BUTTON} w-full justify-center`}>
            Add credit
          </Link>
        )}
      </div>
    </Popover>
  );
}
