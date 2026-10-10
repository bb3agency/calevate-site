"use client";

import { formatCountOf } from "@/components/ui";
import { DNC_LIST_LIMIT, MAX_NUMBERS_PER_ADD, useDncList, type DncSource } from "@/lib/api/dnc";
import type { Session } from "@/lib/api/client";
import { useOutboundConsentPolicy } from "@/lib/api/outboundConsent";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

import { SOURCE_OPTIONS } from "./sources";

/** The do-not-call screen, declared to the assistant (`lib/copilot/registry.ts`). */
export function useDncCopilot({
  session,
  paste,
  parsed,
  source,
  setSource,
  write,
}: {
  session: Session;
  paste: string;
  parsed: string[];
  source: DncSource;
  setSource: (next: DncSource) => void;
  write: { allowed: boolean; reason: string | null | undefined };
}) {
  const entries = useDncList(session);
  // Same query key as `ConsentPosture`, so this is served from cache, not a second request.
  const policy = useOutboundConsentPolicy(session);
  const tooMany = parsed.length > MAX_NUMBERS_PER_ADD;
  const rows = entries.data;
  const truncated = rows !== undefined && rows.length >= DNC_LIST_LIMIT;

  // Every number here is personal data (hard rule 6): the input is declared `personal`
  // and NO row of the list is declared, only counts. Neither the numbers nor the field is
  // writable by the assistant, because an invented number is a call wrongly stopped or a
  // question answered about somebody else. The reason is a four-value enum and is writable.
  useCopilotSurface({
    route: "/c/{slug}/do-not-call",
    title: "Do-not-call list",
    realm: "client",
    fields: [
      {
        id: "dnc-paste",
        label: "Numbers typed or pasted, to check one or suppress them",
        type: "textarea",
        value: paste,
        writable: false,
        personal: "text",
        help: `A human-supplied list. ${formatCountOf(parsed.length, "number")} parsed so far.`,
      },
      {
        id: "dnc-source",
        label: "Why these numbers are being suppressed",
        type: "select",
        value: source,
        options: SOURCE_OPTIONS.map((option) => ({
          value: option.value,
          label: `${option.label} — ${option.note}`,
        })),
      },
    ],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: rows
          ? "the suppressed list below has loaded"
          : entries.error
            ? "the list failed to load, so no number is shown"
            : "still loading",
      },
      {
        key: "suppressed_count",
        label: "Numbers on the list",
        value: rows === undefined ? "not known" : truncated ? `${rows.length} shown, which is the display ceiling — there may be more` : String(rows.length),
      },
      {
        key: "by_reason",
        label: "Why they are suppressed, by count",
        // Counted over the four KNOWN reasons rather than accumulated into a keyed
        // object: a tally keyed by a server string is `src/lib/lookup.ts`'s hazard in a
        // write position, and the reasons are a fixed set the form already enumerates.
        value: rows
          ? rows.length === 0
            ? "nothing is suppressed"
            : SOURCE_OPTIONS.map(
                (option) =>
                  `${option.label}: ${rows.filter((entry) => entry.source === option.value).length}`,
              ).join(", ")
          : "not known",
      },
      { key: "paste_parsed", label: "Numbers parsed out of the paste box", value: String(parsed.length) },
      {
        key: "paste_over_limit",
        label: "Is the pasted list over the per-add ceiling?",
        value: tooMany ? `yes — the ceiling is ${MAX_NUMBERS_PER_ADD} per add` : "no",
      },
      {
        key: "requires_opt_in",
        label: "Does this account refuse to dial a number with no opt-in on file?",
        value:
          policy.data === undefined
            ? "not known"
            : policy.data.outbound_requires_consent
              ? "yes — a number with no consent record is refused as no_consent_record"
              : "no — a number with no consent record is dialled, which is the default",
      },
      {
        key: "may_change",
        label: "May this session add or remove numbers?",
        value: write.allowed ? "yes" : `no — ${write.reason ?? "no reason given"}`,
      },
    ],
    apply: (items) => {
      for (const item of items) {
        if (item.field_id !== "dnc-source") continue;
        const next = SOURCE_OPTIONS.find((option) => option.value === asText(item.value));
        if (next !== undefined) setSource(next.value);
      }
    },
  });

}
