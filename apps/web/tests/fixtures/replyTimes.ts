import type {
  AgentReplyTimes,
  ClientReplyTimes,
  ReplyTimeFigures,
  ReplyTimeReport,
  SlowCall,
} from "@/lib/api/replyTimes";

const TENANT = "019f0000-0000-7000-8000-0000000000a1";
const AGENT = "019f0000-0000-7000-8000-0000000000b1";
export const SLOW_CALL_ID = "019f0000-0000-7000-8000-0000000000c1";

export function figures(over: Partial<ReplyTimeFigures> = {}): ReplyTimeFigures {
  return {
    calls: 14,
    calls_measured: 12,
    reply_typical_ms: 812.4,
    reply_slow_ms: 1460,
    reply_worst_ms: 6210,
    first_token_typical_ms: 305,
    first_token_slow_ms: 520,
    calls_over_target: 3,
    slow_reply_problems: 1,
    turns: 96,
    model_errors: 2,
    rescues: 1,
    interruptions: 7,
    long_silences: 4,
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
  reply_median_ms: 1900,
  reply_p90_ms: 5400,
  reply_max_ms: 6210,
  first_token_p90_ms: 780,
  slow_reply: true,
  model_errors: 2,
  ...over,
});

export function replyTimeReport(over: Partial<ReplyTimeReport> = {}): ReplyTimeReport {
  return {
    window_days: 7,
    target_ms: 500,
    complete: true,
    empty_reason: null,
    overall: figures(),
    by_client: [
      client(),
      client({
        tenant_id: "019f0000-0000-7000-8000-0000000000a2",
        client_name: "Sri Dental",
        client_slug: "sri-dental",
        ...figures({ calls: 2, calls_measured: 2, reply_slow_ms: null, calls_over_target: 0 }),
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
    worst_calls: [slowCall()],
    ...over,
  };
}
