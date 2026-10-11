import type { LanguageStyle, SpokenStyleList } from "@/lib/api/spokenStyle";

/**
 * Ops > Spoken style (D-744): one language with one entry of every kind and every status,
 * so a sweep covers each piece of markup the review screen paints.
 */
export const TELUGU_STYLE: LanguageStyle = {
  language: "te-IN",
  name: "Telugu",
  register_name: "Neutral spoken Telugu",
  review: "needs_native_review",
  reviewed_by: "Sri",
  reviewed_on: "2026-10-11",
  total: 6,
  approved: 2,
  unpublished_changes: 1,
  publish_confirmation: "publish_spoken_style:te-IN",
  history: [
    {
      reviewer_name: "Sri",
      reviewed_on: "2026-10-11",
      published_at: "2026-10-11T08:00:00Z",
      published_by: "0192f0aa-7777-7000-8000-0000000000e1",
      note: "first pass",
    },
  ],
  entries: [
    {
      kind: "register",
      key: "line",
      status: "approved",
      origin: "file",
      value: { text: "Everyday spoken Telugu, neutral for both Telangana and Andhra." },
      published_value: { text: "Everyday spoken Telugu, neutral for both Telangana and Andhra." },
      unpublished: false,
    },
    {
      kind: "swap",
      key: "ధన్యవాదాలు",
      status: "approved",
      origin: "file",
      value: { formal: "ధన్యవాదాలు", spoken: "thanks అండి", in_prompt: true },
      published_value: { formal: "ధన్యవాదాలు", spoken: "thanks అండి", in_prompt: true },
      unpublished: true,
    },
    {
      kind: "swap",
      key: "ధర",
      status: "retired",
      origin: "file",
      value: null,
      published_value: { formal: "ధర", spoken: "price", in_prompt: false },
      unpublished: false,
    },
    {
      kind: "filler",
      key: "sare-andi",
      status: "needs_review",
      origin: "file",
      value: { text: "సరే అండి", use: "Acknowledging what the caller said." },
      published_value: { text: "సరే అండి", use: "Acknowledging what the caller said." },
      unpublished: false,
    },
    {
      kind: "number_rule",
      key: "prices",
      status: "needs_review",
      origin: "file",
      value: { text: 'Prices in English words: "one twenty rupees".' },
      published_value: { text: 'Prices in English words: "one twenty rupees".' },
      unpublished: false,
    },
    {
      kind: "example",
      key: "retail",
      status: "needs_review",
      origin: "file",
      value: {
        turns: [
          { speaker: "caller", text: "మీ దగ్గర ఎండు మిర్చి దొరుకుతుందా అండి?" },
          { speaker: "agent", text: "హా అండి, చెప్తాను. మీకు whole chilli కావాలా, powder కావాలా?" },
        ],
      },
      published_value: null,
      unpublished: false,
    },
    {
      kind: "opening",
      key: "inbound",
      status: "needs_review",
      origin: "file",
      value: { text: "నమస్కారం అండి, {business} కి call చేసినందుకు thanks." },
      published_value: { text: "నమస్కారం అండి, {business} కి call చేసినందుకు thanks." },
      unpublished: false,
    },
  ],
};

export const STYLE_LIST: SpokenStyleList = {
  languages: [
    {
      language: "te-IN",
      name: "Telugu",
      register_name: "Neutral spoken Telugu",
      review: "needs_native_review",
      reviewed_by: "Sri",
      reviewed_on: "2026-10-11",
      total: 6,
      approved: 2,
      unpublished_changes: 1,
    },
    {
      language: "hi-IN",
      name: "Hindi",
      register_name: "Everyday spoken Hindi (Hindustani)",
      review: "needs_native_review",
      reviewed_by: null,
      reviewed_on: null,
      total: 40,
      approved: 0,
      unpublished_changes: 0,
    },
  ],
};
