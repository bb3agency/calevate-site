import type { AccountImprove, WeeklySummary } from "@/lib/api/accountImprove";
import type { TeachQuestion } from "@/lib/api/teachQuestions";

/** The account Improve read of a new account: no calls anywhere yet (`GET /v1/improve`). */
export const EMPTY_ACCOUNT_IMPROVE: AccountImprove = {
  window_days: 30,
  numbers: { numbers: [], min_recent_placed: 30, min_baseline_placed: 60, drop_ratio: 0.6 },
  compare: {
    holders: [],
    best_id: null,
    differences: [],
    min_answered: 20,
    min_judged: 10,
    early_seconds: 20,
    total_spend_inr: "0.00",
    total_goals: 0,
    total_cost_per_goal_inr: null,
  },
  patterns: { patterns: [], min_holders: 2 },
  follow_ups: { hot_leads: 0, callbacks_due: 0 },
  contacts: { on_dnc: 0, unreachable: 0, called_too_often: 0, too_often_days: 7 },
  fixes: [],
};

const weeks = (rates: number[]) =>
  rates.map((answered, i) => ({ week_start: `2026-10-${String(5 + i * 7).padStart(2, "0")}`, placed: 100, answered }));

/** Every section with data: a number that dropped, a best campaign, a pattern, spend, fixes. */
export const FULL_ACCOUNT_IMPROVE: AccountImprove = {
  window_days: 30,
  numbers: {
    numbers: [
      {
        e164: "+918000000001",
        weeks: weeks([50, 52, 48, 10]),
        recent_placed: 100,
        recent_rate: 0.1,
        baseline_placed: 300,
        baseline_rate: 0.5,
        dropped: true,
      },
      {
        e164: "+918000000002",
        weeks: weeks([40, 41]),
        recent_placed: 12,
        recent_rate: null,
        baseline_placed: 40,
        baseline_rate: null,
        dropped: false,
      },
    ],
    min_recent_placed: 30,
    min_baseline_placed: 60,
    drop_ratio: 0.6,
  },
  compare: {
    holders: [
      {
        kind: "campaign",
        id: "camp-best",
        name: "Rytu Khata installs",
        placed: 80,
        answered: 40,
        goals: 20,
        answer_rate: 0.5,
        goal_rate: 0.5,
        early_rate: 0.1,
        drop_off_share: 0.3,
        spend_inr: "200.00",
        cost_per_goal_inr: "10.00",
      },
      {
        kind: "campaign",
        id: "camp-other",
        name: "Renewals",
        placed: 90,
        answered: 30,
        goals: 3,
        answer_rate: 0.3333,
        goal_rate: 0.1,
        early_rate: 0.4,
        drop_off_share: 0.6,
        spend_inr: "150.00",
        cost_per_goal_inr: "50.00",
      },
      {
        kind: "inbound_line",
        id: "line-1",
        name: "Front desk",
        placed: 25,
        answered: 25,
        goals: 0,
        answer_rate: 1,
        goal_rate: 0,
        early_rate: 0,
        drop_off_share: null,
        spend_inr: "40.00",
        cost_per_goal_inr: null,
      },
    ],
    best_id: "camp-best",
    differences: [
      {
        kind: "opening_length",
        best: "8 words",
        others: "30 words",
        instruction:
          "Make the opening line shorter, about 8 words, as on “Rytu Khata installs”, which reaches its goal most often. Keep the AI and recording notices it says. Keep the steps as they are.",
      },
      { kind: "calling_hours", best: "10:00-13:00", others: "all day", instruction: null },
    ],
    min_answered: 20,
    min_judged: 10,
    early_seconds: 20,
    total_spend_inr: "390.00",
    total_goals: 23,
    total_cost_per_goal_inr: "16.96",
  },
  patterns: {
    patterns: [
      {
        kind: "said_again",
        label: "Said the same line again",
        calls: 7,
        holders: 3,
        agents: [{ id: "agent-1", name: "Asha" }],
      },
    ],
    min_holders: 2,
  },
  follow_ups: { hot_leads: 4, callbacks_due: 2 },
  contacts: { on_dnc: 3, unreachable: 5, called_too_often: 2, too_often_days: 7 },
  fixes: [
    {
      kind: "pip_repair",
      holder_kind: "campaign",
      holder_id: "camp-other",
      holder_name: "Renewals",
      at: "2026-11-22T05:00:00Z",
      detail: null,
    },
    {
      kind: "best_hours",
      holder_kind: "campaign",
      holder_id: "camp-best",
      holder_name: "Rytu Khata installs",
      at: "2026-11-21T05:00:00Z",
      detail: "10:00-13:00",
    },
    {
      kind: "pip_notices",
      holder_kind: "inbound_line",
      holder_id: "line-1",
      holder_name: "Front desk",
      at: "2026-11-20T05:00:00Z",
      detail: null,
    },
  ],
};

export const WEEKLY_SUMMARY: WeeklySummary = {
  id: "sum-1",
  week_start: "2026-11-16",
  paragraph: "Your agents answered half the people they called. Most stopped at the price step. Rytu Khata installs did best.",
  figures: { calls: 120, answer_rate: 0.5, goals: 23, fixes: 4, best_name: "Rytu Khata installs" },
  created_at: "2026-11-23T02:20:00Z",
};

export const CALLER_QUESTION: TeachQuestion = {
  key: "delivery",
  question: "Do you deliver to Guntur?",
  topic: "Delivery",
  why: "callers",
  callers: 6,
  times: 8,
  agent_ids: ["agent-1", "agent-2"],
  latest_call_id: "call-1",
  latest_at: "2026-11-22T05:00:00Z",
  example: null,
  draft: null,
  draft_source_kind: null,
  draft_source_label: null,
  drafting: false,
};
