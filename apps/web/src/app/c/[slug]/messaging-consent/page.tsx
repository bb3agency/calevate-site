"use client";

import { useState } from "react";

import { Drawer } from "@/components/console/drawer";
import { PageHeader } from "@/components/console/pageHeader";
import { RestrictionNote, SECONDARY_BUTTON } from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";

import { ConsentLookup } from "./ConsentLookup";
import { useConsentForm } from "./consentForm";
import { useConsentCopilot } from "./copilot";
import { HowItWorks } from "./HowItWorks";
import { RecordConsent } from "./RecordConsent";

/**
 * Messaging consent (SEC-COMP §4): the record of who said we may message them.
 *
 * Checking a number is the screen's job; recording an answer is the rarer one and opens in
 * a drawer. THIS IS NOT CONSENT TO BE CALLED: a campaign's `consent_source` and a callback
 * never satisfy it, a follow-up still passes the do-not-call gate first, and every
 * sentence here that could read as clearance for a CALL is absent or names its gate.
 * Expired is not green: the verdict renders the server's `messageable`, so a year-old
 * grant reads as not messageable with the date it lapsed.
 */
export default function MessagingConsentPage() {
  const session = useClientSession();
  const form = useConsentForm(session);
  const [recording, setRecording] = useState(false);

  // Recording is `leads:dispatch`, the authority that causes a person to be contacted,
  // because an opt-in is that decision. The lookup is `leads:read` and is never gated.
  const write = useWriteAccess(
    session,
    "leads:dispatch",
    "record what a customer said about being messaged",
  );

  useConsentCopilot(form, write);


  const openRecord = () => {
    // Opened from a verdict, the number just checked is the one being recorded against.
    if (form.lookupPhone.trim() && !form.phone.trim()) form.setPhone(form.lookupPhone.trim());
    setRecording(true);
  };

  return (
    <div className="space-y-6 pb-12">
      <PageHeader
        description="Who has agreed to receive WhatsApp messages from you. Campaign follow-ups are only sent to people recorded here — and this is a separate permission from calling, which is governed by the do-not-call list."
        actions={
          write.allowed ? (
            <button type="button" onClick={openRecord} className={SECONDARY_BUTTON}>
              Record an answer
            </button>
          ) : undefined
        }
      />

      <RestrictionNote reason={write.reason} />

      {/* The question people arrive with, and the one thing everyone with access may do. */}
      <ConsentLookup
        form={form}
        recordAction={
          write.allowed ? (
            <button
              type="button"
              onClick={openRecord}
              className="rounded-sm text-[13px] font-medium text-brand-strong underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
            >
              Record what they said
            </button>
          ) : undefined
        }
      />

      <HowItWorks />

      <Drawer
        open={recording && write.allowed}
        onClose={() => setRecording(false)}
        title="Record what a customer said"
        width="md"
      >
        <RecordConsent form={form} />
      </Drawer>
    </div>
  );
}
