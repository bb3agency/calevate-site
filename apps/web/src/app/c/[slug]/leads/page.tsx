"use client";

import { useSearchParams } from "next/navigation";

import { LeadsScreen } from "./LeadsScreen";

/**
 * `/c/{slug}/leads` — the CRM table (D-21, SURFACES §2).
 *
 * A route module keeps the chrome and hands off (UX-DOCTRINE §6): it may export only
 * `default` (D-196), so the screen cannot be split by extraction while it lives here.
 *
 * Keyed on the query string because the lens is seeded from `?status=` and
 * `?campaign_id=` once, at mount: a link to another stage followed from this screen (a
 * Pip chart) would otherwise change the URL and leave the table on the old filter.
 */
export default function LeadsPage() {
  const query = useSearchParams().toString();
  return <LeadsScreen key={query} />;
}
