import type {
  AgentReplyTimes,
  AgentTurnSplit,
  ClientReplyTimes,
  ReplyTimeFigures,
  ReplyTimeReport,
  SlowCall,
  TurnSplit,
} from "@/lib/api/replyTimes";

const TENANT = "019f0000-0000-7000-8000-0000000000a1";
const AGENT = "019f0000-0000-7000-8000-0000000000b1";
export const SLOW_CALL_ID = "019f0000-0000-7000-8000-0000000000c1";

export function figures(over: Partial<ReplyTimeFigures> = {}): ReplyTimeFigures {
  return {
    calls: 14,
    calls_measured: 12,
    calls_answer_measured: 10,
    answer_typical_ms: 1312.4,
    answer_slow_ms: 2460,
    answer_worst_ms: 7210,
    first_sound_typical_ms: 812.4,
    first_sound_slow_ms: 1460,
    first_sound_worst_ms: 6210,
    first_token_typical_ms: 305,
    first_token_slow_ms: 520,
    calls_over_target: 3,
    slow_reply_problems: 1,
    turns: 96,
    model_errors: 2,
    rescues: 1,
    interruptions: 7,
    long_silences: 4,
    knowledge_turns: 18,
    ...over,
  };
}

const client = (over: Partial<ClientReplyTimes> = {}): ClientReplyTimes => ({
  tenant_id: TENANT,
  client_name: "Raghava Organics",
  client_slug: "raghava",
  ...figures(),
  ...over,
});

const agent = (over: Partial<AgentReplyTimes> = {}): AgentReplyTimes => ({
  tenant_id: TENANT,
  client_name: "Raghava Organics",
  client_slug: "raghava",
  agent_id: AGENT,
  agent_name: "Receptionist",
  ...figures(),
  ...over,
});

export function split(over: Partial<TurnSplit> = {}): TurnSplit {
  return {
    turn_detection: "ear",
    calls_timed: 6,
    turns_timed: 41,
    answer_ms: 1380,
    answer_slow_ms: 2240,
    first_sound_ms: 990,
    wait_before_decision_ms: 520,
    recogniser_ms: 210,
    ear_check_ms: 310,
    model_first_sentence_ms: 640,
    voice_ms: 220,
    model_asked_ms: -140,
    turns_filler_first: 5,
    turns_estimated: 5,
    ...over,
  };
}

const agentSplit = (over: Partial<AgentTurnSplit> = {}): AgentTurnSplit => ({
  tenant_id: TENANT,
  client_name: "Raghava Organics",
  client_slug: "raghava",
  agent_id: AGENT,
  agent_name: "Anjali",
  ...split(),
  ...over,
});

const slowCall = (over: Partial<SlowCall> = {}): SlowCall => ({
  call_id: SLOW_CALL_ID,
  tenant_id: TENANT,
  client_name: "Raghava Organics",
  client_slug: "raghava",
  agent_id: AGENT,
  agent_name: "Receptionist",
  started_at: "2026-10-14T05:30:00Z",
  voice_tier: "studio",
  turns: 9,
  answer_median_ms: 2400,
  answer_p90_ms: 6400,
  answer_max_ms: 7210,
  first_sound_median_ms: 1900,
  first_sound_p90_ms: 5400,
  first_token_p90_ms: 780,
  slow_reply: true,
  model_errors: 2,
  knowledge_turns: 3,
  ...over,
});

export function replyTimeReport(over: Partial<ReplyTimeReport> = {}): ReplyTimeReport {
  return {
    window_days: 7,
    typical_target_ms: 1600,
    slow_target_ms: 2200,
    complete: true,
    empty_reason: null,
    overall: figures(),
    by_client: [
      client(),
      client({
        tenant_id: "019f0000-0000-7000-8000-0000000000a2",
        client_name: "Sri Dental",
        client_slug: "sri-dental",
        ...figures({ calls: 2, calls_measured: 2, answer_slow_ms: null, calls_over_target: 0 }),
      }),
    ],
    by_agent: [agent()],
    agents_total: 1,
    by_tier: [
      { tier: "clear", ...figures({ calls_over_target: 0 }) },
      { tier: "studio", ...figures() },
    ],
    by_day: [
      { day: "2026-10-13", ...figures({ calls_over_target: 0 }) },
      { day: "2026-10-14", ...figures() },
    ],
    by_setting: [
      { setting: "turn_detection", value: "ear", ...figures() },
      { setting: "known_facts", value: "not_recorded", ...figures({ calls_over_target: 0 }) },
    ],
    split_by_turn_detection: [
      split(),
      split({
        turn_detection: "timer",
        turns_timed: 30,
        answer_ms: 1710,
        answer_slow_ms: null,
        recogniser_ms: null,
        ear_check_ms: null,
        wait_before_decision_ms: 800,
      }),
    ],
    split_by_agent: [agentSplit(), agentSplit({ turn_detection: "timer", ear_check_ms: null })],
    worst_calls: [slowCall()],
    ...over,
  };
}
