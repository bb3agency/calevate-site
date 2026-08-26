"use client";

import { useMe } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { examplesFor, type VerticalExamples } from "@/lib/verticalExamples";

/**
 * This tenant's example text, for a screen inside `/c/<slug>`.
 *
 * The console had the same defect as the onboarding wizard and one layer further from
 * anybody who would notice: "e.g. Clinic hours" on the knowledge base, "Our consultation
 * fee is ₹500…" on the gap answer, "so we can route urgent cases to a doctor first" on an
 * extracted field, and a script-assistant brief that opened "We are a dental clinic in
 * Hyderabad." A property office's own staff read those, not an operator — so the wrong
 * trade is being described to the person whose trade it is.
 *
 * `/v1/me` already carries `organization.vertical_template`, so nothing new is fetched:
 * TanStack Query dedupes on the key, and every screen in this realm already asks for it.
 * While it is in flight `examplesFor(undefined)` returns the trade-neutral set, which
 * reads as an instruction rather than as a different business — so the placeholder never
 * flickers from one trade's example to another's.
 */
export function useVerticalExamples(): VerticalExamples {
  const session = useClientSession();
  const me = useMe(session);
  return examplesFor(me.data?.organization?.vertical_template);
}
