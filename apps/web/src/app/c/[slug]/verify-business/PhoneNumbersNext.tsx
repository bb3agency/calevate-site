"use client";

import Link from "next/link";

import { Card, SECONDARY_BUTTON_SM } from "@/components/ui";
import { numberStage, useOwnNumbersStatus } from "@/lib/api/ownNumbers";
import { useClientRealm } from "@/lib/api/session";

/**
 * Verifying the business is step 1 of getting a phone number in its own name (D-693); this
 * card says where steps 2 and 3 stand and leads to them. Renders nothing where numbers are
 * not bought that way, and nothing while the answer is unknown — the journey's own screen
 * reports a failed read, so this one does not repeat it.
 */
export function PhoneNumbersNext() {
  const { session, href } = useClientRealm();
  const status = useOwnNumbersStatus(session);
  if (!status.data?.available) return null;
  const step = status.data.step;
  const sentence =
    numberStage(status.data) !== "journey"
      ? "Add credit first to get your own number."
      : step === "ready"
        ? "Approved. You can pick a number now."
        : step === "business_details"
          ? "Next: approval of your business details."
          : step === "price"
            ? "Ready. Numbers are not on sale yet."
            : step === "workspace"
              ? "Your calling account is being set up."
              : "Verify your business first.";
  return (
    <Card title="Phone numbers in your business's name">
      <p className="text-sm text-ink">{sentence}</p>
      <Link href={href(`/c/${session.orgSlug}/phone-number`)} className={`mt-3 ${SECONDARY_BUTTON_SM}`}>
        Go to phone numbers
      </Link>
    </Card>
  );
}
