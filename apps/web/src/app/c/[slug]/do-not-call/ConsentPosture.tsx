"use client";

import { useActionFeedback } from "@/components/arc/feedback";
import { SavedTick } from "@/components/console/savedTick";
import { ProblemNotice, RestrictionNote, Skeleton, ToggleSwitch } from "@/components/ui";
import { type Session } from "@/lib/api/client";
import { useWriteAccess } from "@/lib/api/hooks";
import {
  useOutboundConsentPolicy,
  useSetOutboundConsentPolicy,
} from "@/lib/api/outboundConsent";

import { WhyTip } from "../agreements/_ui/WhyTip";
import { DNC_COPY as COPY, DNC_KEPT as KEPT } from "./copy";

const LABEL = COPY.postureLabel;

/**
 * Whether this account dials a number with no opt-in on file: one setting, one switch.
 *
 * The two sentences under the row are what keep the switch from reading as permission,
 * so both stay on screen in BOTH positions and never move behind an ⓘ (UX-DOCTRINE §8.7):
 * the person most likely to misread "off" is the one who has just turned it off.
 */
export function ConsentPosture({ session }: { session: Session }) {
  const policy = useOutboundConsentPolicy(session);
  const set = useSetOutboundConsentPolicy(session);
  // The switch waits while it writes and a failure is said under it, so nothing is toasted;
  // "Saved" appears beside the switch.
  const setFeedback = useActionFeedback(set, { errorDisplay: "inline" });
  const write = useWriteAccess(session, "org:manage", "change who this account may call");
  const enabled = policy.data?.outbound_requires_consent;

  return (
    <section aria-label="Who this account may call" className="border-t border-line pt-1">
      {policy.isPending && <Skeleton rows={1} label={COPY.postureSaving} />}
      {policy.error != null && <ProblemNotice error={policy.error} />}
      {enabled !== undefined && (
        <>
          {/* The whole label is the switch's target, not a bare 20px track: a setting row
              whose control is a lone switch would be too small a target on a phone. */}
          <ToggleSwitch
            label={LABEL}
            hint={COPY.postureHint}
            checked={enabled}
            // Disabled while the write is in flight too: a switch that moves back under
            // the reader's finger when the request fails is worse than one that waits.
            disabled={!write.allowed || setFeedback.status === "pending"}
            onChange={(next) => setFeedback.run(next)}
            className="py-3.5"
          />
          <SavedTick at={set.isSuccess ? set.submittedAt : 0} />
          <div className="space-y-1 pb-2">
            <p className="text-meta text-ink-muted">{enabled ? KEPT.postureOn : KEPT.postureOff}</p>
            <p className="flex flex-wrap items-center gap-x-1 text-meta text-ink-muted">
              {KEPT.notPermission}
              <WhyTip about="the opt-in setting" label="Why?">
                <p>{enabled ? COPY.postureOnWhy : COPY.postureOffWhy}</p>
              </WhyTip>
            </p>
          </div>
          <RestrictionNote reason={write.reason} />
          {set.error != null && <ProblemNotice error={set.error} />}
        </>
      )}
    </section>
  );
}
