"use client";

import type { UseQueryResult } from "@tanstack/react-query";

import type { LegalReadiness } from "@/lib/api/agreements";
import type { AutodialerNotice } from "@/lib/api/autodialerNotice";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText, noFill, type CopilotFact, type CopilotFillItem } from "@/lib/copilot/types";

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
    facts: agreementsFacts(readiness.data, readiness.error),
    apply: noFill,
  });
}

function agreementsFacts(data: LegalReadiness | undefined, error: unknown): CopilotFact[] {
  const readiness = { data, error };
  return [
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
  ];
}

export type NoticeDraft = {
  accessProvider: string;
  objective: string;
  notifiedOn: string;
  numbers: string;
};

/**
 * The same screen once the autodialler notice has loaded, with its record form declared.
 *
 * Registered from inside the notice panel, so it is the innermost (live) surface while the
 * form is on screen; it carries the agreements facts too, so nothing the page declared is
 * lost. The assistant may fill the four facts of the letter; recording it, and the
 * withdrawal, stay the owner's own press. The acceptance tick is still not declared.
 */
export function useAutodialerNoticeCopilot({
  readiness,
  notice,
  draft,
  apply,
  canWrite,
}: {
  /** Absent only where the panel is rendered on its own (its tests). */
  readiness?: LegalReadiness;
  notice: AutodialerNotice;
  draft: NoticeDraft;
  apply: (patch: Partial<NoticeDraft>) => void;
  canWrite: boolean;
}) {
  useCopilotSurface({
    route: "/c/{slug}/agreements",
    title: "Your agreements",
    realm: "client",
    fields: [
      { id: "notice-operator", label: "Which operator did you tell?", type: "text", value: draft.accessProvider, writable: canWrite },
      { id: "notice-date", label: "What is the date on your letter?", type: "date", value: draft.notifiedOn, writable: canWrite },
      { id: "notice-objective", label: "What did you tell them the calls are for?", type: "text", value: draft.objective, writable: canWrite },
      {
        id: "notice-numbers",
        label: "Which numbers did your letter say the calls come from? (one per line)",
        type: "textarea",
        value: draft.numbers,
        writable: canWrite,
        personal: "phone",
      },
    ],
    facts: [
      ...(readiness ? agreementsFacts(readiness, null) : []),
      { key: "notice_recorded", label: "Is an autodialler notice on file?", value: notice.recorded ? "yes" : "no" },
      ...(notice.recorded
        ? [
            { key: "notice_state", label: "The notice on file is", value: notice.state ?? "unknown" },
            { key: "notice_effective", label: "Is the notice on file in effect?", value: notice.effective ? "yes" : "no" },
          ]
        : []),
      {
        key: "notice_missing_numbers",
        label: "Agent numbers the notice does not name",
        value: String(notice.undeclared_clis.length),
      },
    ],
    apply: (items: CopilotFillItem[]) => {
      const patch: Partial<NoticeDraft> = {};
      for (const item of items) {
        const raw = asText(item.value);
        if (item.field_id === "notice-operator") patch.accessProvider = raw;
        if (item.field_id === "notice-date") patch.notifiedOn = raw;
        if (item.field_id === "notice-objective") patch.objective = raw;
        if (item.field_id === "notice-numbers") patch.numbers = raw;
      }
      apply(patch);
    },
  });
}
