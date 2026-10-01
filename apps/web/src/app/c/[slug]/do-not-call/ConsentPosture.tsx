"use client";

import { SettingRow } from "@/components/console/settingRow";
import { ProblemNotice, RestrictionNote, Skeleton, ToggleSwitch } from "@/components/ui";
import { type Session } from "@/lib/api/client";
import { useWriteAccess } from "@/lib/api/hooks";
import {
  useOutboundConsentPolicy,
  useSetOutboundConsentPolicy,
} from "@/lib/api/outboundConsent";

const LABEL = "Only call people who have opted in";

/**
 * Whether this account dials a number with no opt-in on file — one setting, one row.
 *
 * The two sentences under the row are what keep the switch from reading as permission,
 * so both stay on screen in BOTH positions and never move behind an ⓘ (UX-DOCTRINE §8.7):
 * the person most likely to misread "off" is the one who has just turned it off.
 */
export function ConsentPosture({ session }: { session: Session }) {
  const policy = useOutboundConsentPolicy(session);
  const set = useSetOutboundConsentPolicy(session);
  const write = useWriteAccess(session, "org:manage", "change who this account may call");
  const enabled = policy.data?.outbound_requires_consent;

  return (
    <section aria-label="Who this account may call" className="border-t border-line pt-1">
      {policy.isPending && <Skeleton rows={1} label="Loading this account's calling posture" />}
      {policy.error != null && <ProblemNotice error={policy.error} />}
      {enabled !== undefined && (
        <>
          <SettingRow
            label={LABEL}
            hint="Checked before every outbound call, campaigns included."
            control={
              <ToggleSwitch
                label={<span className="sr-only">{LABEL}</span>}
                checked={enabled}
                // Disabled while the write is in flight too: a switch that moves back under
                // the reader's finger when the request fails is worse than one that waits.
                disabled={!write.allowed || set.isPending}
                onChange={(next) => set.mutate(next)}
                className="inline-flex"
              />
            }
          />
          <div className="space-y-1 pb-2">
            <p className="text-[13px] text-ink-muted">
              {enabled
                ? "A number with no opt-in on file is refused rather than dialled. Capture the opt-in first — a form, a booking, a reply, or an inbound call from the customer."
                : "Numbers with no opt-in on file are dialled. Turn this on if this account only contacts its own existing customers about their own bookings."}
            </p>
            <p className="text-[12px] text-ink-faint">
              Leaving this off is not permission to call strangers. It means this system stops
              checking, and the responsibility for who is called stays with your business.
            </p>
          </div>
          <RestrictionNote reason={write.reason} />
          {set.error != null && <ProblemNotice error={set.error} />}
        </>
      )}
    </section>
  );
}
