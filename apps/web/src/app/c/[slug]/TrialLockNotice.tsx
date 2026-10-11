"use client";

import { RowLink } from "@/components/console/checklist";
import { NoticeBox } from "@/components/ui";
import { useClientRealm } from "@/lib/api/session";
import { useShellWallet } from "@/lib/api/wallet";

/** What a free-trial account cannot use yet, in the client's words (D-697). */
export const TRIAL_LOCK_COPY = {
  numbers: {
    title: "Your own phone number comes after the trial",
    body: "Test calls ring from a shared Calevate number until then.",
    info: "Add credit, then verify your business, and you can buy a number in your business's name.",
  },
  campaigns: {
    title: "Campaigns open once you add credit",
    body: "Until then, try your agents with test calls from your dashboard.",
    info: "Add credit and verify your business to call your leads.",
  },
  kyc: {
    title: "Business verification opens once you add credit",
    body: "You can accept the no-cold-calls promise below and place test calls now.",
    info: "Verifying your business comes next, after you add credit.",
  },
  agents: {
    title: "Your agents can place test calls during the trial",
    body: "An agent that only answers calls needs your own number, which comes after the trial.",
    info: "Your own number comes after you add credit and verify your business. Until then, set an agent to place calls and try it from your dashboard.",
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
    <NoticeBox
      tone="neutral"
      title={copy.title}
      info={copy.info}
      action={<RowLink href={href(`/c/${session.orgSlug}/billing?tab=credits`)}>Add credit to go live</RowLink>}
    >
      {copy.body}
    </NoticeBox>
  );
}
