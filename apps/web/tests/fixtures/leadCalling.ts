/** A client's lead-calling plan as `GET /v1/lead-calling` answers it with no plan saved. */
export const LEAD_CALLING_DEFAULT = {
  hours_start: "09:00:00",
  hours_end: "21:00:00",
  days: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
  holidays: [],
  after_hours: "next_open",
  detect_machines: false,
  new_leads_follow_up: { id: "00000000-0000-7000-8000-000000000001", name: "Call new leads", status: "live" },
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
