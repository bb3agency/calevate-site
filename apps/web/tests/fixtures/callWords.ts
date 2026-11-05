import type { CallWordDetail, CallWordsList } from "@/lib/api/callWords";

/**
 * Ops > Call words (G-C2): one list of each shape, one waiting for the founder's words and
 * one already edited, so a sweep covers every piece of markup the screen paints. The words
 * are English placeholders; the real lists are the founder's.
 */
export const CALL_WORDS: CallWordsList = {
  about: "FOUNDER-OWNED. The words the call checks listen for.",
  entries: [
    {
      key: "detection.stalls",
      group: "detection",
      shape: "pattern",
      value: "let me check",
      shipped: "let me check",
      edited: false,
      changed_at: null,
      asked_for: "'let me check and tell you' in Telugu letters and in Hindi letters.",
      note: null,
      confirmation: "change_call_words:detection.stalls",
    },
    {
      key: "detection.topic.pricing",
      group: "detection",
      shape: "list",
      value: ["price", "cost", "rate"],
      shipped: ["price", "cost"],
      edited: true,
      changed_at: "2026-11-06T05:00:00Z",
      asked_for: "Each topic's trigger words in Telugu letters and Hindi letters.",
      note: null,
      confirmation: "change_call_words:detection.topic.pricing",
    },
    {
      key: "optout.not_now",
      group: "optout",
      shape: "table",
      value: { te: { latin: "ippudu", native: "now" } },
      shipped: { te: { latin: "ippudu", native: "now" } },
      edited: false,
      changed_at: null,
      asked_for: null,
      note: "'Now' a few words before an opt-out makes it 'not now'.",
      confirmation: "change_call_words:optout.not_now",
    },
  ],
};

export const PRICING_DETAIL: CallWordDetail = {
  ...CALL_WORDS.entries[1],
  history: [
    {
      value: ["price", "cost", "rate"],
      note: "rate is asked often",
      changed_by: "0192f0aa-7777-7000-8000-0000000000e1",
      changed_at: "2026-11-06T05:00:00Z",
    },
  ],
};
