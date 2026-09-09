"use client";

import { useState } from "react";

import { RestrictionNote } from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import {
  useIngestActivity,
  useLeadSources,
  useMetaRedrive,
  useMetaSetup,
  useTestWebhook,
  type LeadSourceDryRun,
} from "@/lib/api/leadSources";

import { DeliveryLog } from "./DeliveryLog";
import { MetaCard } from "./MetaCard";
import { SourcesPanel } from "./SourcesPanel";
import { SAMPLE_PAYLOAD, TestLeadCard } from "./TestLeadCard";
import { useLeadSourcesCopilot } from "./copilot";

/**
 * Lead sources (SURFACES §2b): inbound webhook ingest made visible.
 *
 * The route is thin and this is the screen (UX-DOCTRINE §6): the four panels below are
 * four subjects, and each one is its own module — `SourcesPanel` (create, rotate, switch
 * off), `TestLeadCard` (rehearse), `MetaCard` (setup material and recovery),
 * `DeliveryLog` (what actually arrived). What stays here is the state the panels share
 * and the assistant declaration built from it.
 *
 * ## What the provisioning pass changed
 *
 * The cards used to take a raw UUID in a text box, under a line reading "Don't have an
 * ID? Ask us — lead sources are provisioned by Calevate", because nothing in the product
 * could create one: every `inbound_webhooks` row was an operator running SQL.
 * `GET/POST /v1/lead-sources` ended that, so the ID boxes are pickers over the client's
 * own sources and the sentence they stood under is gone.
 *
 * Three rules the sources panel obeys, each of which is a way this screen could lie:
 *
 * - **The secret is on screen exactly once.** The create and rotate responses are the
 *   only place the plaintext exists outside the database; the list carries a
 *   fingerprint, and nothing here re-fetches a value.
 * - **Rotation states its deadline.** "Rotated" without a deadline reads as "the old one
 *   is dead", and it is not — the old secret keeps working for the grace window, which
 *   is the whole reason a client can rotate without dropping leads.
 * - **§52 holds for the list too.** A failed read renders a refusal and NO list — never
 *   "no lead sources yet", which on this screen would invite a client to create a second
 *   source for a form that is already wired up.
 *
 * The screen prints no `<h1>`: the app shell already renders one from the nav list.
 */
export function LeadSourcesScreen() {
  const session = useClientSession();

  const sources = useLeadSources(session);
  const activity = useIngestActivity(session);
  const test = useTestWebhook(session);
  const metaSetup = useMetaSetup(session);
  const redrive = useMetaRedrive(session);

  /**
   * D-22 read-only, and the least obvious case on the sweep: the dry-run writes
   * nothing — no lead row, no inbox row, no dial — yet `POST /v1/lead-sources/{id}/test`
   * requires `org:manage`, which is mutating, so an impersonating operator is refused
   * it. That is the server's deliberate call (ingest/routes.py): a dry-run is an action
   * taken ON the client's behalf, not a view of their data, and the activity table
   * below is on `org:read` precisely so support keeps the view without the action.
   *
   * So the button is gated on what the endpoint actually checks, not on what the
   * operation morally is — and BOTH buttons are, because `POST .../meta/setup` is on
   * the same permission for its own reason (its response carries a credential).
   */
  const write = useWriteAccess(session, "org:manage", "test or set up a lead source");

  // Pickers over the client's own sources now that `GET /v1/lead-sources` exists. The
  // state is still an id string, so a request built from it is unchanged — what went
  // away is a client having to know a UUID by heart.
  const [testSourceId, setTestSourceId] = useState("");
  // Separate from the test above on purpose: the two cards are independent tasks and
  // a client wiring up Meta is usually not the same person rehearsing a form post.
  const [metaSourceId, setMetaSourceId] = useState("");
  const [payloadText, setPayloadText] = useState(SAMPLE_PAYLOAD);
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [result, setResult] = useState<LeadSourceDryRun | null>(null);

  useLeadSourcesCopilot({
    sources,
    activity,
    testSourceId,
    setTestSourceId,
    metaSourceId,
    setMetaSourceId,
    payloadText,
    jsonError,
    result,
    write,
  });

  /**
   * A VERDICT IS ABOUT THE INPUTS IT WAS RUN ON, so changing either retracts it.
   *
   * The verdict names steps that passed and failed for one source and one payload. Left
   * standing under an edited payload — or, worse, under a DIFFERENT lead source — it is
   * a specific, confident claim about a request nobody made, and the pass/fail ticks
   * beside it read as the answer for what is on screen now. `/do-not-call` already makes
   * this call in the same words ("a stale verdict beside a changed number is worse than
   * no verdict") and takes the same action; this card is the second of the two and had
   * no such retraction, so an operator could change the source and read the previous
   * source's result as this one's.
   *
   * `test.reset()` as well as the local state, because the refusal rendered from
   * `test.error` is a verdict too — it says why THAT sample was rejected.
   */
  const clearVerdict = () => {
    setResult(null);
    setJsonError(null);
    test.reset();
  };

  const runTest = () => {
    setJsonError(null);
    setResult(null);

    // Parse client-side first: a typo in the JSON is the user's most likely
    // failure, and it deserves a friendly message, not a 422 round-trip.
    let payload: unknown;
    try {
      payload = JSON.parse(payloadText);
    } catch {
      setJsonError(
        "That doesn't look like valid JSON — check for a missing quote, comma or brace.",
      );
      return;
    }
    if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
      setJsonError("The sample must be a JSON object like the pre-filled example.");
      return;
    }

    // The sample goes in the BODY. It carries a phone number — the client's own test
    // number or, sooner or later, a real lead's — and a number in a query string lands
    // in access logs, proxies and browser history (hard rule 6). Only the lead source's
    // UUID is ever in the path.
    test.mutate({ webhookId: testSourceId.trim(), payload }, { onSuccess: setResult });
  };

  return (
    <div className="space-y-5 pb-12">
      <p className="text-sm text-ink-muted">
        Incoming leads from your website forms and ads, with every delivery accounted for.
      </p>

      <RestrictionNote reason={write.reason} />

      <SourcesPanel session={session} canWrite={write.allowed} />

      <TestLeadCard
        sources={sources}
        test={test}
        sourceId={testSourceId}
        onSourceId={(next) => {
          setTestSourceId(next);
          clearVerdict();
        }}
        payloadText={payloadText}
        onPayloadText={(next) => {
          setPayloadText(next);
          clearVerdict();
        }}
        jsonError={jsonError}
        result={result}
        onRun={runTest}
        canWrite={write.allowed}
      />

      <MetaCard
        sources={sources}
        activity={activity}
        metaSetup={metaSetup}
        redrive={redrive}
        sourceId={metaSourceId}
        onSourceId={setMetaSourceId}
        canWrite={write.allowed}
      />

      <DeliveryLog activity={activity} />
    </div>
  );
}
