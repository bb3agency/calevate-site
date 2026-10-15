"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { ExistingNumberGuide } from "@/components/forwarding/ExistingNumberGuide";
import { dismissExistingNumberPrompt } from "@/components/forwarding/ExistingNumberPrompt";
import { PageHeader } from "@/components/console/pageHeader";
import { TEXT_ACTION } from "@/components/console/section";
import { NoticeBox, ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import { useForwarding } from "@/lib/api/forwarding";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";

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
        title="Get your Calevate number first."
        action={
          <Link href={href(`/c/${slug}/phone-number`)} className={TEXT_ACTION}>
            Open phone numbers
          </Link>
        }
      >
        Your existing number forwards its calls to it.
      </NoticeBox>
    );
  } else if (forwarding.data.lines.length > 0) {
    body = (
      <NoticeBox
        tone="ok"
        title="Your existing number is set up."
        action={
          <Link href={settings} className={TEXT_ACTION}>
            Open settings
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
      <PageHeader
        title="Use your existing number"
        description="Keep the number your callers already know. Calls reach your agent through call forwarding on your phone."
      />
      <RestrictionNote reason={write.reason} />
      {body}
    </div>
  );
}
