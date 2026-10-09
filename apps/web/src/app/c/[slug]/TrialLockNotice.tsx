"use client";

import Link from "next/link";
import { Lock } from "lucide-react";

import { NoticeBox } from "@/components/ui";
import { useClientRealm } from "@/lib/api/session";
import { useShellWallet } from "@/lib/api/wallet";

/** What a free-trial account cannot use yet, in the client's words (D-697). */
export const TRIAL_LOCK_COPY = {
  numbers: {
    title: "Your own phone number comes after the trial",
    body: "During your free trial, test calls ring from a shared Calevate number. Add credit, then verify your business, and you can buy a number in your business's name.",
  },
  campaigns: {
    title: "Campaigns open once you add credit",
    body: "During your free trial you can try your agents with test calls from your dashboard. Add credit and verify your business to call your leads.",
  },
  kyc: {
    title: "Business verification opens once you add credit",
    body: "During your free trial you can accept the no-cold-calls promise below and place test calls. Verifying your business comes next, after you add credit.",
  },
  agents: {
    title: "Your agents can place test calls during the trial",
    body: "An agent that only answers calls needs your own phone number, which comes after you add credit and verify your business. Until then, set an agent to place calls and try it from your dashboard.",
  },
} as const;

export type TrialLock = keyof typeof TRIAL_LOCK_COPY;

/**
 * Said at the top of a screen a free-trial account cannot use yet: why, and the one step
 * that opens it. Renders nothing for any other account, and nothing until the shell's wallet
 * read has answered; it never asks for the wallet itself (`useShellWallet`).
 */
export function TrialLockNotice({ lock }: { lock: TrialLock }) {
  const { session, href } = useClientRealm();
  const wallet = useShellWallet(session);
  if (wallet === undefined || wallet.trial?.test_calls_only !== true) return null;
  const copy = TRIAL_LOCK_COPY[lock];
  return (
    <NoticeBox tone="neutral" icon={<Lock aria-hidden className="h-4 w-4" />} title={copy.title}>
      <p>{copy.body}</p>
      <Link
        href={href(`/c/${session.orgSlug}/billing?tab=credits`)}
        className="mt-2 inline-block font-semibold underline underline-offset-2"
      >
        Add credit to go live
      </Link>
    </NoticeBox>
  );
}
