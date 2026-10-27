"use client";

/**
 * Pip's plans (D-893): one card for an action over many records — who, why, when, the
 * estimate, who is left out and why — read from `GET /v1/copilot/plans/{id}`, and the
 * three things a person does with it: approve exactly that plan, stop it, or see how it
 * went. The plan's targets were frozen on the server when it was made; the browser never
 * holds the list, only a page of it when the person opens it.
 */

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { apiRequest, type Session } from "@/lib/api/client";
import { refreshAfterConfirm } from "@/lib/api/copilot";
import type { components } from "@/lib/api/schema";
import { formatINR } from "@/lib/numberDisplay";

type Schemas = components["schemas"];

export type CopilotPlanOut = Schemas["CopilotPlanOut"];
export type CopilotPlanTargetOut = Schemas["CopilotPlanTargetOut"];
export type CopilotPlanTargetPageOut = Schemas["CopilotPlanTargetPageOut"];
export type CopilotPlanPageOut = Schemas["CopilotPlanPageOut"];
export type PlanStatus = CopilotPlanOut["status"];

/** How often a running plan's card re-reads its progress. */
export const PLAN_POLL_MS = 2_500;

/** How many targets one page of the expanded list shows. */
export const PLAN_TARGET_PAGE = 25;

export const planKeys = {
  plan: (org: string, id: string) => ["copilot-plan", org, id] as const,
  targets: (org: string, id: string, offset: number) =>
    ["copilot-plan-targets", org, id, offset] as const,
  recent: (org: string) => ["copilot-plans", org] as const,
};

function planPath(id: string, tail = ""): string {
  return `/v1/copilot/plans/${encodeURIComponent(id)}${tail}`;
}

/** Whether a plan is still doing something a person should watch. */
export function isActive(status: PlanStatus): boolean {
  return status === "approved" || status === "running";
}

/** One plan, polled while it is approved or running and left alone once it has ended. */
export function usePlan(session: Session, planId: string) {
  return useQuery<CopilotPlanOut>({
    queryKey: planKeys.plan(session.orgSlug, planId),
    queryFn: () => apiRequest<CopilotPlanOut>(session, planPath(planId)),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status !== undefined && isActive(status) ? PLAN_POLL_MS : false;
    },
  });
}

/** One page of a plan's targets, read only when the person opens the list. */
export function usePlanTargets(session: Session, planId: string, offset: number, open: boolean) {
  return useQuery<CopilotPlanTargetPageOut>({
    queryKey: planKeys.targets(session.orgSlug, planId, offset),
    queryFn: () =>
      apiRequest<CopilotPlanTargetPageOut>(
        session,
        planPath(planId, `/targets?limit=${PLAN_TARGET_PAGE}&offset=${offset}`),
      ),
    enabled: open,
  });
}

/** The person's recent plans, for the Tasks list. */
export function useRecentPlans(session: Session) {
  return useQuery<CopilotPlanPageOut>({
    queryKey: planKeys.recent(session.orgSlug),
    queryFn: () => apiRequest<CopilotPlanPageOut>(session, "/v1/copilot/plans?limit=10"),
    refetchInterval: (query) =>
      query.state.data?.plans.some((plan) => isActive(plan.status)) ? PLAN_POLL_MS : false,
  });
}

function refreshPlan(client: QueryClient, org: string, plan: CopilotPlanOut): void {
  client.setQueryData(planKeys.plan(org, plan.id), plan);
  void client.invalidateQueries({ queryKey: ["copilot-plan-targets", org, plan.id] });
  void client.invalidateQueries({ queryKey: planKeys.recent(org) });
}

/** Approve exactly this plan — the hash it was shown with is what the server binds. */
export function approvePlan(session: Session, plan: CopilotPlanOut): Promise<CopilotPlanOut> {
  return apiRequest<CopilotPlanOut>(session, planPath(plan.id, "/approve"), {
    method: "POST",
    body: { plan_hash: plan.plan_hash },
  });
}

export function useApprovePlan(session: Session) {
  const client = useQueryClient();
  return useMutation<CopilotPlanOut, unknown, CopilotPlanOut>({
    mutationFn: (plan) => approvePlan(session, plan),
    onSuccess: (plan) => refreshPlan(client, session.orgSlug, plan),
  });
}

/** Re-read a plan and its list after a door other than the plan's own decided it. */
export function refreshPlanById(client: QueryClient, org: string, planId: string): void {
  void client.invalidateQueries({ queryKey: planKeys.plan(org, planId) });
  void client.invalidateQueries({ queryKey: ["copilot-plan-targets", org, planId] });
  void client.invalidateQueries({ queryKey: planKeys.recent(org) });
}

/** Stop a plan: nothing more runs; what already ran stays. */
export function useCancelPlan(session: Session) {
  const client = useQueryClient();
  return useMutation<CopilotPlanOut, unknown, string>({
    mutationFn: (planId) =>
      apiRequest<CopilotPlanOut>(session, planPath(planId, "/cancel"), { method: "POST" }),
    onSuccess: (plan) => refreshPlan(client, session.orgSlug, plan),
  });
}

/** Once a plan has finished, the screens its action touches are refreshed once. */
export function refreshAfterPlan(client: QueryClient, org: string, plan: CopilotPlanOut): void {
  refreshAfterConfirm(client, org, plan.tool);
  void client.invalidateQueries({ queryKey: planKeys.recent(org) });
}

// --- words ------------------------------------------------------------------------------

const STATUS_WORDS: Record<PlanStatus, string> = {
  proposed: "Waiting for your approval",
  approved: "Starting",
  running: "Working on it",
  done: "Finished",
  cancelled: "Stopped",
  expired: "Expired — nothing was done",
};

export function planStatusWords(status: PlanStatus): string {
  return STATUS_WORDS[status];
}

const TARGET_NOUN: Record<CopilotPlanOut["target_type"], [string, string]> = {
  lead: ["lead", "leads"],
  call: ["call", "calls"],
  callback: ["call-back", "call-backs"],
};

/** "1 lead", "240 leads". */
export function countOf(n: number, type: CopilotPlanOut["target_type"]): string {
  const [one, many] = TARGET_NOUN[type];
  return `${n.toLocaleString("en-IN")} ${n === 1 ? one : many}`;
}

/** The estimate as a person reads it: a rupee figure, "Free", or "Not known". */
export function estimateWords(plan: Pick<CopilotPlanOut, "estimate_inr">): string {
  if (plan.estimate_inr === null) return "Not known";
  if (!/^-?\d+(\.\d+)?$/.test(plan.estimate_inr)) return "Not known";
  if (!/[1-9]/.test(plan.estimate_inr)) return "Free";
  return `About ${formatINR(plan.estimate_inr)}`;
}
