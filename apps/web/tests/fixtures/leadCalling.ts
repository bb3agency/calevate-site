/** A client's lead-calling plan as `GET /v1/lead-calling` answers it with no plan saved. */
export const LEAD_CALLING_DEFAULT = {
  calling_agent_id: null,
  wait_seconds: 0,
  hours_start: "09:00:00",
  hours_end: "21:00:00",
  days: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
  holidays: [],
  after_hours: "next_open",
  retry_attempts: 0,
  retry_interval_minutes: 60,
  detect_machines: false,
  updated_at: null,
  window_start: "09:00:00",
  window_end: "21:00:00",
  held_count: 0,
  trial_notice: null,
  always_applied: [
    "Numbers on your do-not-call list, or the national one, are never called.",
    "Calls go out only between 9 AM and 9 PM Indian time, whatever hours you set here.",
  ],
  agents_updated: 0,
};

export const LEAD_CALLING_ROUTES = {
  "/v1/lead-calling": LEAD_CALLING_DEFAULT,
  "/v1/lead-calling/held": { items: [] },
};
