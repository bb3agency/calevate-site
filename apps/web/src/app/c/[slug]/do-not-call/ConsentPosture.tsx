"use client";

import { Card, ProblemNotice, RestrictionNote, Skeleton, ToggleSwitch } from "@/components/ui";
import { type Session } from "@/lib/api/client";
import { useWriteAccess } from "@/lib/api/hooks";
import {
  useOutboundConsentPolicy,
  useSetOutboundConsentPolicy,
} from "@/lib/api/outboundConsent";

/**
 * Who this account may call at all (D-624) — the mirror of the list below it.
 *
 * The do-not-call list names the people we must NOT ring. This switch answers the other
 * half of the same question: whether a number nobody has said anything about may be rung.
 * `check_dispatch` is permissive by default ("absence is not a refusal"), because most
 * dialable numbers have no consent record and refusing all of them would read as an
 * outage. An account whose outbound is service or transactional — reminders,
 * confirmations, follow-ups to the business's own customers — wants the other answer, and
 * this is where it says so once rather than intending it per campaign.
 *
 * ## The copy has to be honest about OFF, which is why the note is not decoration
 *
 * OFF does not mean "you may call strangers". It means this system stops being the thing
 * that checks, and the obligation stays exactly where TCCCPR put it — on the sender. A
 * switch labelled only by what ON does would read as permission, which is the one reading
 * that could cost a client every telecom resource they hold (Reg 25(6)).
 *
 * ## Why this card renders for readers who cannot move it
 *
 * Reading is `org:read` and moving it is `org:manage`, so a staff member who has just seen
 * a campaign row refused can open this screen and find out what the refusal means. The
 * switch itself is disabled with the reason said out loud rather than the card being
 * hidden — a control that vanishes teaches nobody why.
 */
export function ConsentPosture({ session }: { session: Session }) {
  const policy = useOutboundConsentPolicy(session);
  const set = useSetOutboundConsentPolicy(session);
  const write = useWriteAccess(session, "org:manage", "change who this account may call");

  const enabled = policy.data?.outbound_requires_consent;

  return (
    <Card title="Who this account may call">
      {policy.isPending && <Skeleton rows={1} label="Loading this account's calling posture" />}

      {policy.error != null && <ProblemNotice error={policy.error} />}

      {enabled !== undefined && (
        <>
          <ToggleSwitch
            label="Only call people who have opted in"
            hint="Checked before every outbound call, campaigns included."
            checked={enabled}
            // Disabled while the write is in flight as well as when the session may not
            // make it: a switch that moves back under the reader's finger when the request
            // fails is worse than one that waits.
            disabled={!write.allowed || set.isPending}
            onChange={(next) => set.mutate(next)}
          >
            <p className="mt-2 text-sm text-ink-muted">
              {enabled
                ? "A number with no opt-in on file is refused rather than dialled. Capture the opt-in first — a form, a booking, a reply, or an inbound call from the customer."
                : "Numbers with no opt-in on file are dialled. Turn this on if this account only contacts its own existing customers about their own bookings."}
            </p>
          </ToggleSwitch>

          {/* The sentence that keeps the switch from reading as permission. It stays on
              screen in BOTH positions, because the person most likely to misread it is the
              one who has just turned it off. */}
          <p className="mt-3 text-xs text-ink-faint">
            Leaving this off is not permission to call strangers. It means this system stops
            checking, and the responsibility for who is called stays with your business.
          </p>

          <div className="mt-3">
            <RestrictionNote reason={write.reason} />
          </div>

          {set.error != null && (
            <div className="mt-3">
              <ProblemNotice error={set.error} />
            </div>
          )}
        </>
      )}
    </Card>
  );
}
