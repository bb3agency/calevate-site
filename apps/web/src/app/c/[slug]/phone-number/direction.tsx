"use client";

/**
 * WHAT A NUMBER IS FOR — the three legs, and the one sentence about the third.
 *
 * Two screens ask this: the purchase, which records an intent, and the assignment, which
 * is what actually puts the number on an agent. They are one question and they are worded
 * here once, because the risky half is a sentence about the law and two copies of it
 * would drift apart exactly where that costs the most.
 *
 * ## Inbound and outbound are not the same kind of choice
 *
 * Answering a call on a number this account holds is unrestricted. Calling OUT is not:
 * TRAI direction RG-25/(18)/2023-QoS (E-10291), 18 Jun 2024 addresses the SENDER of
 * promotional, service and transactional voice calls and names the delegation chain, so
 * an ordinary 10-digit number reaches service and reminder calls only through the
 * confirmation `SenderAttestation.tsx` records, and reaches marketing campaigns not at
 * all (`docs/evidence/primary-legal-findings-2026-09-20.md` §1).
 *
 * Three radio buttons reading "inbound / outbound / both" with nothing beside them would
 * offer the second and third as ordinary settings. So choosing either POINTS AT the
 * confirmation that already exists on this page rather than restating it: the statement,
 * its version and its withdrawal all live in that panel, and a second wording of what a
 * client is accepting is how the two come apart.
 *
 * Shown for an ORDINARY number only. On a registered 140 or 160 header the confirmation
 * does not apply and the API refuses one, so a note pointing at it would send a client
 * looking for a control that is not there.
 */

import { NoticeBox } from "@/components/ui";
import type { CallDirection } from "@/lib/api/numberProvisioning";
import { Term } from "@/lib/glossary";

/** The three legs, in the order a client meets them — answering first. */
export const DIRECTIONS: { value: CallDirection; label: string; hint: string }[] = [
  {
    value: "inbound",
    label: "Answer calls to this number",
    hint: "Anyone who rings it reaches your agent.",
  },
  {
    value: "outbound",
    label: "Call out from this number",
    hint: "Your agent dials from it — reminders, follow-ups and call-backs.",
  },
  {
    value: "both",
    label: "Both",
    hint: "It answers callers, and your agent dials out from it.",
  },
];

/** The series the sender confirmation applies to — an ordinary 10-digit connection. */
const ORDINARY = "standard";

export function OutboundRestriction({
  direction,
  series,
}: {
  direction: CallDirection;
  /** The server's own class for this number, derived from its prefix. */
  series: string;
}) {
  if (direction === "inbound" || series !== ORDINARY) return null;
  return (
    <NoticeBox tone="warn">
      <p>
        Calling out from an ordinary number is not free of rules. Your agent can dial from
        it only once you have confirmed that your business is the sender of those calls,
        which is the panel on the number itself — and marketing campaigns need a{" "}
        <Term id="series140" term="140-series" /> number whichever option you pick here.
      </p>
    </NoticeBox>
  );
}
