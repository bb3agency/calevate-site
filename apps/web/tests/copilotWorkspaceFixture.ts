/**
 * The assistant page's wire, as the server answers it — shared by the workspace tests and
 * the accessibility sweep so both render the same rows.
 *
 * The rows carry the realistic worst case where it matters (break-ui): a long instruction,
 * a long refusal sentence, a waiting approval from a background task, a running task with
 * five steps, a routine switched off.
 */

import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];

const NOW = "2026-10-09T03:30:00Z";

export const PENDING_APPROVAL: Schemas["CopilotActionOut"] = {
  id: "0192f0aa-0000-7000-8000-00000000a001",
  realm: "client",
  tool: "dnc_add",
  tier: "confirm",
  status: "pending_approval",
  source: "job",
  object_type: "lead",
  object_id: "0192f0aa-0000-7000-8000-0000000001ea",
  args: null,
  summary: "Add this caller to your do-not-call list so no campaign rings them again.",
  refusal_reason: null,
  can_undo: false,
  undoable_until: null,
  undone_at: null,
  decided_at: null,
  job_id: "0192f0aa-0000-7000-8000-00000000b001",
  created_at: NOW,
};

export const DONE_ACTION: Schemas["CopilotActionOut"] = {
  ...PENDING_APPROVAL,
  id: "0192f0aa-0000-7000-8000-00000000a002",
  tool: "lead_set_status",
  tier: "immediate",
  status: "done",
  source: "interactive",
  summary: "Marked this lead as Contacted. It was New.",
  can_undo: true,
  undoable_until: "2099-01-01T00:00:00Z",
  job_id: null,
};

export const REFUSED_ACTION: Schemas["CopilotActionOut"] = {
  ...PENDING_APPROVAL,
  id: "0192f0aa-0000-7000-8000-00000000a003",
  tool: "campaign_launch",
  status: "refused",
  source: "job",
  summary: null,
  refusal_reason:
    "Calls are paused for this account until your business verification is approved, so the campaign was not started.",
  job_id: null,
};

export const RUNNING_JOB: Schemas["CopilotJobOut"] = {
  id: "0192f0aa-0000-7000-8000-00000000b001",
  status: "running",
  goal: "Morning call-backs: Call back yesterday's missed leads.",
  screen_route: "/c/{slug}/assistant",
  progress: [
    { at: NOW, kind: "step", text: "Looked up yesterday's missed calls: 14 leads." },
    {
      at: NOW,
      kind: "approval",
      text: "Waiting for your approval: start a call-back campaign for 14 leads.",
      action_id: PENDING_APPROVAL.id,
    },
  ],
  result: null,
  error_code: null,
  created_at: NOW,
  started_at: NOW,
  finished_at: null,
};

export const ROUTINE_ON: Schemas["CopilotRoutineOut"] = {
  id: "0192f0aa-0000-7000-8000-00000000c001",
  name: "Morning call-backs",
  instruction: "Call back yesterday's missed leads and tell me who did not pick up twice.",
  schedule: { days: ["mon", "tue", "wed", "thu", "fri"], time: "09:30" },
  enabled: true,
  next_run_at: "2026-10-12T04:00:00Z",
  last_run_at: NOW,
  created_at: NOW,
  updated_at: NOW,
};

export const ROUTINE_OFF: Schemas["CopilotRoutineOut"] = {
  ...ROUTINE_ON,
  id: "0192f0aa-0000-7000-8000-00000000c002",
  name: "Friday lead summary for the whole sales team at the Kukatpally branch",
  instruction:
    "Summarise this week's leads: how many came in, who is hot, who has not been called back, and which campaign brought the most.",
  schedule: { days: ["fri"], time: "17:00" },
  enabled: false,
  next_run_at: null,
};

export const PREVIEW: Schemas["CopilotApprovalPreviewOut"] = {
  action_id: PENDING_APPROVAL.id,
  tool: "dnc_add",
  object_type: "lead",
  title: "Stop calling this number",
  summary: "Add this caller to your do-not-call list.",
  current: "Can be called",
  proposed: "Never called again",
  cost: null,
  reversal: "Removing a number from the list needs the owner, on the Do not call screen.",
  still_applies: true,
  refusal: null,
  expires_at: "2026-10-10T03:30:00Z",
};

/** The routes the client workspace reads on arrival, with each list populated. */
export function workspaceRoutes(): Record<string, unknown> {
  return {
    "/v1/copilot/approvals": { actions: [PENDING_APPROVAL], has_more: false },
    "/v1/copilot/jobs": { jobs: [RUNNING_JOB] },
    "/v1/copilot/routines": { routines: [ROUTINE_ON, ROUTINE_OFF] },
    "/v1/copilot/conversation?limit=50": { turns: [], has_more: false },
    "/v1/copilot/actions?limit=30": {
      actions: [DONE_ACTION, REFUSED_ACTION, PENDING_APPROVAL],
      has_more: true,
    },
  };
}
