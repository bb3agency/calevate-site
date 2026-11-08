/**
 * Row keys for the delivery log, out of the page module (D-196).
 *
 * IT LIVED IN `app/c/[slug]/lead-sources/page.tsx` AND WAS EXPORTED FROM IT, which
 * `next build` refuses: a Next.js page module may export only `default` and a fixed set of
 * route fields, so `export function deliveryRowKeys` failed the production build with
 * *"deliveryRowKeys is not a valid Page export field"*. Nothing imported it — it was
 * exported to be reachable — so the constraint cost nothing but a build.
 *
 * It is a MODULE rather than a private function for the reason it was exported in the
 * first place: it is a pure function with a real argument behind it, worth testing on its
 * own, and a page file is the one place in this app where making something testable
 * breaks the build. Here it cannot bite again.
 *
 * ── WHY THE KEY IS WHAT IT IS ──
 *
 * `lead_source_id` + `event_key` is not unique. `apps/api/ingest/routes.py` maps two
 * keyspaces onto one `lead_source_id` and discards the provider, so two rows can carry an
 * identical identity and React renders a duplicate-key warning — which the suite printed
 * on a green run, the state in which the next collision hides.
 *
 * The real fix is one server field (the provider on `IngestActivityItemOut`); the route
 * has the value in hand and throws it away. That is `apps/api`'s to make, and this file
 * cannot reach it.
 *
 * What this does instead is refuse to be wrong with the payload it has: identity plus its
 * OCCURRENCE COUNT among identical identities, unique by construction whatever the server
 * sends. The rejected alternative is the array index, which is unique too and re-keys
 * every row whenever the 30-second refetch reorders the table — this key survives a
 * reorder for every row whose identity is unambiguous, i.e. all of them until the server
 * actually collides. Delete it, and this comment, when the field lands.
 */

import type { IngestActivityItem } from "@/lib/api/leadSources";
import { lookup } from "@/lib/lookup";

export function deliveryRowKeys(
  items: readonly IngestActivityItem[],
): [IngestActivityItem, string][] {
  const seen = new Map<string, number>();
  return items.map((item) => {
    const identity = `${item.lead_source_id}-${item.event_key}`;
    const nth = seen.get(identity) ?? 0;
    seen.set(identity, nth + 1);
    return [item, nth === 0 ? identity : `${identity}#${nth}`];
  });
}

/**
 * The delivery log's reason, in the owner's words. The server sends the CODE it recorded
 * on the inbox row (`apps/api/ingest/meta.py`, `graph.py`, `routes.py`, and the verdicts
 * `ingest/service.ingest_lead` raises); a code on a client screen is internal speak, so a
 * code with no sentence here gets the general one rather than its own spelling.
 */
const DELIVERY_PROBLEM: Record<string, string> = {
  ingest_no_phone: "No phone number came with this lead, so there was no one to call.",
  ingest_no_agent: "No agent is set to call leads from this source.",
  agent_not_published: "The agent for this source is not live yet.",
  push_not_a_lead: "This did not look like a lead, so nothing was saved.",
  meta_lead_retrieval_unavailable: "We could not read this lead yet. Finish Meta setup to fetch it.",
  meta_page_token_not_configured: "We could not read this lead yet. Finish Meta setup to fetch it.",
  meta_page_token_invalid: "Your Meta connection stopped working. Connect your Page again in Meta setup.",
  meta_leads_retrieval_denied: "Meta did not let us read this lead. Check your Page's lead access in Meta setup.",
  meta_lead_not_readable: "Meta would not give us this lead. It may have been deleted.",
  meta_lead_had_no_answers: "This lead came with no answers, so there was no one to call.",
  meta_graph_malformed_response: "Meta sent this lead in a form we could not read.",
  meta_rate_limited: "Meta was busy. It will send this lead again.",
  meta_graph_unavailable: "Meta was busy. It will send this lead again.",
  meta_graph_unreachable: "Meta did not answer. It will send this lead again.",
  meta_lead_interrupted: "This lead was interrupted. Meta will send it again.",
};

export function deliveryProblem(code: string | null | undefined): string | null {
  if (!code) return null;
  return lookup(DELIVERY_PROBLEM, code) ?? "We could not use this lead.";
}
