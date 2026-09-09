"use client";

import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";
import type {
  LeadSourceDryRun,
  useIngestActivity,
  useLeadSources,
} from "@/lib/api/leadSources";
import type { WriteAccess } from "@/lib/api/hooks";

/*
 * THIS SCREEN, DECLARED TO THE ASSISTANT (`lib/copilot/registry.ts`).
 *
 * ## The rehearsal payload is `personal`, and it is not writable
 *
 * `payloadText` is a sample form post, and the moment somebody debugs a real one they
 * paste a real customer into it — a name, a number, whatever their form collects. So it
 * leaves as `«PRIVATE_1»` (D-127 G-2) rather than as itself, and the assistant is told
 * how many bytes and whether it parses instead of what it says. It is `writable: false`
 * because a payload the model composed would be a rehearsal of a request nobody makes.
 *
 * ## Neither is the app secret, which is not declared at all
 *
 * It is a credential. The two SOURCE PICKERS are writable: they hold ids off this
 * account's own list, and picking the wrong one is the mistake this screen's own
 * retraction logic exists to catch.
 *
 * The activity table is declared as COUNTS. Its rows carry `event_key` and an error
 * string off a real ingest, which is the last place a customer's details would still
 * be recognisable.
 */
export function useLeadSourcesCopilot({
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
}: {
  sources: ReturnType<typeof useLeadSources>;
  activity: ReturnType<typeof useIngestActivity>;
  testSourceId: string;
  setTestSourceId: (id: string) => void;
  metaSourceId: string;
  setMetaSourceId: (id: string) => void;
  payloadText: string;
  jsonError: string | null;
  result: LeadSourceDryRun | null;
  write: WriteAccess;
}) {
  useCopilotSurface({
    route: "/c/{slug}/lead-sources",
    title: "Where your leads come from",
    realm: "client",
    fields: [
      {
        id: "lead-source-test-source",
        label: "Which lead source the rehearsal runs against",
        type: "select",
        value: testSourceId,
        options: (sources.data?.items ?? []).map((row) => ({ value: row.id, label: row.source })),
      },
      {
        id: "lead-source-meta-source",
        label: "Which lead source the Meta setup is for",
        type: "select",
        value: metaSourceId,
        options: (sources.data?.items ?? [])
          .filter((row) => row.source === "meta_lead_ads")
          .map((row) => ({ value: row.id, label: row.source })),
      },
      {
        id: "lead-source-payload",
        label: "Rehearsal payload (JSON)",
        type: "textarea",
        value: payloadText,
        writable: false,
        personal: "text",
        help: "A form post to rehearse against. It often holds a real customer, so the assistant is told about it rather than shown it.",
      },
    ],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: sources.data
          ? "the lead sources below have loaded"
          : sources.error
            ? "the lead sources failed to load, so none is listed"
            : "still loading",
      },
      ...(sources.data
        ? [
            { key: "sources_total", label: "Lead sources configured", value: String(sources.data.items.length) },
            {
              key: "sources_active",
              label: "Of those, switched on",
              value: String(sources.data.items.filter((row) => row.active).length),
            },
            {
              key: "source_kinds",
              label: "What kind each one is",
              value: sources.data.items.map((row) => row.source).join(", ") || "none configured",
            },
            {
              key: "sources_rotating",
              label: "Sources with an old signing secret still inside its grace period",
              value: String(sources.data.items.filter((row) => row.previous_secret_expires_at !== null).length),
            },
          ]
        : []),
      {
        key: "activity_state",
        label: "Has the recent ingest activity loaded?",
        value: activity.data ? "yes" : activity.error ? "no — it failed to load" : "still loading",
      },
      ...(activity.data
        ? [
            { key: "activity_rows", label: "Recent ingest attempts listed", value: String(activity.data.items.length) },
            {
              key: "activity_outcomes",
              label: "How those attempts ended",
              value: (["accepted", "rejected", "processing"] as const)
                .map(
                  (outcome) =>
                    `${outcome}: ${activity.data.items.filter((item) => item.outcome === outcome).length}`,
                )
                .join(", "),
            },
            {
              key: "activity_recoverable",
              label: "Rejected attempts that could be sent again",
              value: String(
                activity.data.items.filter((item) => item.outcome === "rejected" && item.recoverable).length,
              ),
            },
            {
              key: "activity_deduplicated",
              label: "Duplicate posts dropped across those attempts",
              value: String(activity.data.items.reduce((total, item) => total + item.deduplicated, 0)),
            },
          ]
        : []),
      {
        key: "payload_parses",
        label: "Does the rehearsal payload parse as JSON?",
        value: jsonError === null ? "yes" : `no — ${jsonError}`,
      },
      {
        key: "verdict_on_screen",
        label: "Is there a rehearsal verdict on screen?",
        value: result === null ? "no" : "yes — the reader can see which steps passed",
      },
      {
        key: "may_test",
        label: "May this session run a rehearsal or set up Meta?",
        value: write.allowed ? "yes" : `no — ${write.reason ?? "no reason given"}`,
      },
    ],
    apply: (items) => {
      for (const item of items) {
        const wanted = asText(item.value);
        if (item.field_id === "lead-source-test-source") {
          if ((sources.data?.items ?? []).some((row) => row.id === wanted)) setTestSourceId(wanted);
        } else if (item.field_id === "lead-source-meta-source") {
          if ((sources.data?.items ?? []).some((row) => row.id === wanted && row.source === "meta_lead_ads")) {
            setMetaSourceId(wanted);
          }
        }
      }
    },
  });
}
