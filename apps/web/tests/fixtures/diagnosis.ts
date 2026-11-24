import type { HolderDiagnosis } from "@/lib/api/improve";

/** A campaign's or line's Improve readings with no calls yet (`GET …/diagnosis`). */
export const EMPTY_DIAGNOSIS: HolderDiagnosis = {
  window_days: 30,
  drop_off: { judged_calls: 0, min_calls: 10, steps: [], worst_step: null },
  mistakes: [],
  early_hang_ups: {
    answered: 0,
    early: 0,
    rate: null,
    others_answered: 0,
    others_rate: null,
    min_answered: 20,
    early_seconds: 20,
  },
  refusal_reasons: [],
};

/** The same with every card's data drawn: steps, a mistake, early hang-ups and reasons. */
export const FULL_DIAGNOSIS: HolderDiagnosis = {
  window_days: 30,
  drop_off: {
    judged_calls: 12,
    min_calls: 10,
    worst_step: 2,
    steps: [
      { step: 1, name: "Greets", reached: 12, not_reached: 0, unclear: 0, lost_here: 0 },
      { step: 2, name: "Books a visit", reached: 6, not_reached: 5, unclear: 1, lost_here: 5 },
    ],
  },
  mistakes: [
    {
      kind: "said_again",
      label: "Said the same line again",
      calls: 3,
      last_call_id: "call-1",
      last_seen_at: "2026-11-20T10:00:00Z",
      status: "repairing",
    },
  ],
  early_hang_ups: {
    answered: 40,
    early: 8,
    rate: 0.2,
    others_answered: 30,
    others_rate: 0.1,
    min_answered: 20,
    early_seconds: 20,
  },
  refusal_reasons: [{ reason: "price", calls: 4 }],
};
