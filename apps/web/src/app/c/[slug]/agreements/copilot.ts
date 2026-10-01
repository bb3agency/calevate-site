"use client";

import type { UseQueryResult } from "@tanstack/react-query";

import type { LegalReadiness } from "@/lib/api/agreements";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

/**
 * The agreements screen, declared to the assistant (`lib/copilot/registry.ts`).
 *
 * Read-only on purpose: accepting an agreement is a legal commitment a person makes by
 * ticking a box, never something an assistant fills in, so the tick box is not declared
 * at all rather than declared unwritable. Nothing here is personal.
 */
export function useAgreementsCopilot(readiness: UseQueryResult<LegalReadiness>) {
  useCopilotSurface({
    route: "/c/{slug}/agreements",
    title: "Your agreements",
    realm: "client",
    fields: [],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: readiness.data
          ? "the agreements below have loaded"
          : readiness.error
            ? "the agreements failed to load, so this account's standing is not shown"
            : "still loading",
      },
      ...(readiness.data
        ? [
            {
              key: "verdict",
              label: "Where this account stands",
              value: readiness.data.verdict,
            },
            {
              key: "may_operate",
              label:
                "May this account operate on the agreements it has accepted?",
              value: readiness.data.may_operate ? "yes" : "no",
            },
            {
              key: "outstanding_documents",
              label: "Agreements still to accept",
              value: String(readiness.data.outstanding_documents),
            },
            {
              key: "blockers",
              label: "Things blocking acceptance",
              value: String(readiness.data.blockers.length),
            },
            {
              key: "pending_legal_review",
              label: "Is a document waiting on our own legal review?",
              value: readiness.data.pending_legal_review ? "yes" : "no",
            },
            {
              key: "can_accept",
              label: "May this session accept on the account's behalf?",
              value: readiness.data.can_accept
                ? "yes"
                : `no — ${readiness.data.can_accept_reason ?? "no reason given"}`,
            },
            {
              key: "documents",
              label: "The documents listed, and whether each blocks operating",
              value: readiness.data.documents
                .map(
                  (doc) =>
                    `${doc.title} (${doc.blocking ? "blocking" : "for reference"})`,
                )
                .join("; "),
            },
          ]
        : []),
    ],
    apply: noFill,
  });

}
