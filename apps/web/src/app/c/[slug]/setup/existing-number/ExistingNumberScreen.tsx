"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { ExistingNumberGuide } from "@/components/forwarding/ExistingNumberGuide";
import { dismissExistingNumberPrompt } from "@/components/forwarding/ExistingNumberPrompt";
import { PageHeader } from "@/components/console/pageHeader";
import { NoticeBox, PRIMARY_BUTTON, ProblemNotice, RestrictionNote, SECONDARY_BUTTON, Skeleton } from "@/components/ui";
import { useForwarding } from "@/lib/api/forwarding";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";

import { SETUP } from "../_ui/copy";
import { Why } from "@/components/why";

/**
 * ONBOARDING: "Use your existing number" (D-746), offered once the business has its
 * Calevate number. Skippable; skipping only hides the prompt on this device.
 */
export function ExistingNumberScreen() {
  const { session, href } = useClientRealm();
  const router = useRouter();
  const slug = session.orgSlug;
  const forwarding = useForwarding(session);
  const write = useWriteAccess(session, "org:manage", "set up your existing number");
  const settings = href(`/c/${slug}/settings/phone-numbers`);
  const leave = () => {
    dismissExistingNumberPrompt(slug);
    router.push(href(`/c/${slug}`));
  };

  let body;
  if (forwarding.isLoading) {
    body = <Skeleton rows={4} label="Loading your numbers" />;
  } else if (forwarding.error || !forwarding.data) {
    body = <ProblemNotice error={forwarding.error ?? new Error("Your numbers did not load.")} onRetry={() => void forwarding.refetch()} />;
  } else if (forwarding.data.calevate_numbers.length === 0) {
    body = (
      <NoticeBox
        tone="neutral"
        title={SETUP.needNumber}
        action={
          <Link href={href(`/c/${slug}/phone-number`)} className={PRIMARY_BUTTON}>
            {SETUP.needNumberAction}
          </Link>
        }
        info="Your existing number forwards its calls to it."
      />
    );
  } else if (forwarding.data.lines.length > 0) {
    body = (
      <NoticeBox
        tone="ok"
        title={SETUP.existingDone}
        action={
          <Link href={settings} className={SECONDARY_BUTTON}>
            {SETUP.existingSettings}
          </Link>
        }
      />
    );
  } else {
    const target = forwarding.data.calevate_numbers[0]!;
    body = (
      <ExistingNumberGuide
        session={session}
        calevateNumber={target.e164}
        calevateNumberId={target.id}
        allowed={write.allowed}
        testingAvailable={forwarding.data.testing_available}
        onSkip={leave}
        onDone={() => router.push(settings)}
      />
    );
  }

  return (
    <div className="max-w-2xl space-y-6 pb-12">
      <div>
        <PageHeader title={SETUP.existingTitle} description={SETUP.existingHint} />
        <Why label={SETUP.existingWhy}>Calls reach your agent through call forwarding on your phone.</Why>
      </div>
      <RestrictionNote reason={write.reason} />
      {body}
    </div>
  );
}
