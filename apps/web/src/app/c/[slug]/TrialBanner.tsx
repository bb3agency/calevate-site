"use client";

import Link from "next/link";
import { Gift, Hourglass } from "lucide-react";

import { NOTICE_TONES } from "@/components/ui";
import { useClientRealm } from "@/lib/api/session";
import { activeTrial, trialEndsAt, trialTimeLeft, useWallet, type Wallet } from "@/lib/api/wallet";

/**
 * The free trial, said on every screen while it runs (D-536).
 *
 * Mounted in the shell rather than on one screen because a trial changes what every money
 * sentence in the console means: an empty wallet stops nothing, so a client who only ever
 * opens Leads or Calls must still be able to learn that calls are on us, and until when.
 *
 * It reads the same `GET /v1/billing/wallet` the dashboard tile and the credits screen read
 * (same query key, so no extra request), and the trial block on it is the one the
 * operator's trial panel writes — dates and a day count, never what the trial costs us.
 *
 * Renders NOTHING while the read is in flight, when it fails and when no trial is running.
 * That is the opposite of the §52 rule for a figure, and deliberately: this strip is
 * additional good news, and every screen that states a balance already renders its own
 * loading and failure arms. A strip that said "we could not check your trial" on every
 * page for an account that has never had one would be noise on the common case.
 */
export function TrialBanner() {
  const { session, href } = useClientRealm();
  const wallet = useWallet(session);
  return <TrialStrip wallet={wallet.data} creditsHref={href(`/c/${session.orgSlug}/billing?tab=credits`)} />;
}

/** The strip itself, separate from the read so the copy can be tested against a clock. */
export function TrialStrip({
  wallet,
  creditsHref,
  now,
}: {
  wallet: Wallet | undefined;
  creditsHref: string;
  now?: Date;
}) {
  if (wallet?.trial?.test_calls_only) {
    return <TestCallTrialStrip wallet={wallet} creditsHref={creditsHref} now={now} />;
  }
  const trial = activeTrial(wallet);
  if (!wallet || trial === null) return null;
  const left = trialTimeLeft(trial, now);
  const ends = trialEndsAt(trial);

  if (!left.lastDay) {
    return (
      <div
        role="status"
        className={`flex items-start gap-3 border-b px-4 py-2 text-sm lg:px-8 ${NOTICE_TONES.ok}`}
      >
        <Gift aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
        <p className="min-w-0">
          <span className="font-semibold">
            You&apos;re on a free trial until {ends} — {left.text}.
          </span>{" "}
          Calls are on us until then: nothing is taken from your calling credit, and an
          empty balance does not stop your agents making or answering calls.
        </p>
      </div>
    );
  }

  /* THE LAST 24 HOURS: the same fact, plus what happens next and the one action that
     changes it. Only a prepaid account is asked to top up — an invoiced account has no
     wallet, and after its trial calls go back on the monthly invoice. */
  return (
    <div
      role="status"
      className={`flex flex-wrap items-start gap-x-3 gap-y-2 border-b px-4 py-2 text-sm lg:px-8 ${NOTICE_TONES.warn}`}
    >
      <Hourglass aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
      <p className="min-w-0 flex-1">
        <span className="font-semibold">
          Your free trial ends {ends} — {left.text}.
        </span>{" "}
        {wallet.prepaid
          ? "After that, calls are paid from your calling credit, and with no credit your agents stop making outgoing calls and stop answering incoming ones. Add credit now so calls carry on when the trial ends."
          : "After that, your calls are billed on your monthly invoice as usual."}
      </p>
      {wallet.prepaid && (
        <Link
          href={creditsHref}
          className="shrink-0 rounded-sm font-semibold underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-warn focus-visible:ring-offset-2 touch:min-h-11"
        >
          Add credit
        </Link>
      )}
    </div>
  );
}

/**
 * A FREE TRIAL FOR TRYING CALEVATE (D-697): test calls only, until the account adds credit.
 * Said on every screen because every screen the trial locks is reached from here, and the
 * one action that unlocks them is the same everywhere.
 */
function TestCallTrialStrip({
  wallet,
  creditsHref,
  now,
}: {
  wallet: Wallet;
  creditsHref: string;
  now?: Date;
}) {
  const trial = activeTrial(wallet);
  const link = (
    <Link
      href={creditsHref}
      className="shrink-0 rounded-sm font-semibold underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 touch:min-h-11"
    >
      Add credit
    </Link>
  );
  if (trial === null) {
    return (
      <div
        role="status"
        className={`flex flex-wrap items-start gap-x-3 gap-y-2 border-b px-4 py-2 text-sm lg:px-8 ${NOTICE_TONES.warn}`}
      >
        <Hourglass aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
        <p className="min-w-0 flex-1">
          <span className="font-semibold">Your free trial has ended.</span> Add credit to
          continue: it opens business verification, your own phone number and live calls.
        </p>
        {link}
      </div>
    );
  }
  const left = trialTimeLeft(trial, now);
  const minutes =
    trial.minutes_left === null || trial.minutes_left === undefined
      ? ""
      : `, ${trial.minutes_left} free ${trial.minutes_left === 1 ? "minute" : "minutes"} left`;
  return (
    <div
      role="status"
      className={`flex flex-wrap items-start gap-x-3 gap-y-2 border-b px-4 py-2 text-sm lg:px-8 ${left.lastDay ? NOTICE_TONES.warn : NOTICE_TONES.ok}`}
    >
      <Gift aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
      <p className="min-w-0 flex-1">
        <span className="font-semibold">
          You&apos;re on a free trial until {trialEndsAt(trial)} — {left.text}
          {minutes}.
        </span>{" "}
        Try your agents with test calls from your dashboard. Answering calls, campaigns, your
        own number and business verification open once you add credit.
      </p>
      {link}
    </div>
  );
}
