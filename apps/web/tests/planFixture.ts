import type { CopilotPlanOut } from "@/lib/copilot/plans";

export const PLAN_ID = "01900000-0000-7000-8000-0000000000aa";

/** One plan as `GET /v1/copilot/plans/{id}` answers it (`copilot/plan_schemas.CopilotPlanOut`). */
export function planFixture(overrides: Partial<CopilotPlanOut> = {}): CopilotPlanOut {
  return {
    id: PLAN_ID,
    tool: "leads_bulk_update",
    origin: "pip",
    target_type: "lead",
    title: "Set 140 leads to contacted",
    why: "You asked to mark last week's missed callers as contacted.",
    who: "Leads that came in 20–26 Oct whose last call was missed",
    run_at: null,
    target_count: 140,
    excluded_count: 0,
    exclusions: [],
    estimate_inr: null,
    estimate_note: "Costs nothing.",
    plan_hash: "a".repeat(64),
    status: "proposed",
    expires_at: "2026-10-28T10:00:00Z",
    approved_at: null,
    started_at: null,
    finished_at: null,
    done_count: 0,
    skipped_count: 0,
    failed_count: 0,
    pending_count: 140,
    result: null,
    campaign_id: null,
    can_approve: true,
    can_cancel: true,
    created_at: "2026-10-27T10:00:00Z",
    ...overrides,
  };
}
