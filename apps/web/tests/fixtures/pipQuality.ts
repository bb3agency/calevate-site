import type { PipQualityFigures, PipQualityReport } from "@/lib/api/pipQuality";

/** A Pip quality report (D-937): a low `leads` area with one example, a healthy `calls`. */
export function pipFigures(over: Partial<PipQualityFigures> = {}): PipQualityFigures {
  return {
    answers: 10,
    done: 6,
    done_share: 0.6,
    thumbs_up: 3,
    thumbs_down: 1,
    thumbs_down_share: 0.25,
    reasons: [],
    tool_failures: 0,
    permission_refusals: 0,
    actions_done: 4,
    actions_undone: 1,
    actions_failed: 0,
    action_failure_share: 0,
    proposals: 2,
    proposals_accepted: 1,
    proposals_abandoned: 1,
    fell_back: 1,
    first_token_typical_ms: 640,
    first_token_slow_ms: null,
    total_typical_ms: 2100,
    total_slow_ms: null,
    low: [],
    examples: [],
    ...over,
  };
}

export function pipQualityReport(over: Partial<PipQualityReport> = {}): PipQualityReport {
  const leads = pipFigures({
    answers: 6,
    thumbs_up: 1,
    thumbs_down: 4,
    thumbs_down_share: 0.8,
    reasons: [{ reason: "not_done", count: 3 }],
    low: ["thumbs_down"],
    examples: [
      {
        turn_id: "0192f0aa-2222-7000-8000-0000000000b1",
        tenant_id: "0192f0aa-3333-7000-8000-0000000000c1",
        why: "thumbs_down",
        note: "it missed the booking",
      },
    ],
  });
  return {
    realm: "client",
    window_days: 7,
    complete: true,
    questions: 12,
    refusals: [{ reason: "fair_use", count: 2 }],
    overall: pipFigures({ reasons: [{ reason: "not_done", count: 3 }] }),
    by_area: [
      { area: "leads", figures: leads },
      { area: "calls", figures: pipFigures({ answers: 4 }) },
    ],
    by_tool: [
      {
        tool: "lead_set_status",
        area: "leads",
        is_action: true,
        figures: pipFigures({ answers: 5, actions_failed: 1 }),
      },
    ],
    by_provider: [{ provider: "google", answers: 9 }],
    thumbs_down_low_share: 0.4,
    min_votes: 5,
    action_failure_low_share: 0.25,
    min_attempts: 5,
    ...over,
  };
}
