"use client";

/**
 * The assistant workspace's reads and writes: the activity log, the Approvals inbox, the
 * background tasks and the routines (D-694).
 *
 * Every hook goes through `apiRequest` and the generated types, the console's one door. The
 * lists POLL while the workspace is open (the D-24 shape the job card already uses), slower
 * than a running job's card, because what changes here is mostly the person's own doing.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest, type Session } from "@/lib/api/client";
import { refreshAfterConfirm } from "@/lib/api/copilot";
import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];

export type CopilotActionOut = Schemas["CopilotActionOut"];
export type CopilotActionPageOut = Schemas["CopilotActionPageOut"];
export type CopilotJobOut = Schemas["CopilotJobOut"];
export type CopilotJobPageOut = Schemas["CopilotJobPageOut"];
export type CopilotConfirmOut = Schemas["CopilotConfirmOut"];
export type CopilotApprovalPreviewOut = Schemas["CopilotApprovalPreviewOut"];
export type CopilotRoutineOut = Schemas["CopilotRoutineOut"];
export type CopilotRoutineIn = Schemas["CopilotRoutineIn"];
export type CopilotRoutinePatch = Schemas["CopilotRoutinePatch"];
export type CopilotRoutinePageOut = Schemas["CopilotRoutinePageOut"];
export type CopilotRoutineRunOut = Schemas["CopilotRoutineRunOut"];
export type CopilotRoutineRunPageOut = Schemas["CopilotRoutineRunPageOut"];
export type Weekday = CopilotRoutineIn["schedule"]["days"][number];

export type Realm = "client" | "admin";

/** How often the workspace re-reads its lists while it is on screen. */
export const WORKSPACE_POLL_MS = 15_000;

/** One page of the activity log. */
export const ACTIVITY_PAGE = 30;

const key = {
  actions: (realm: Realm, org: string) => ["copilot-actions", realm, org] as const,
  approvals: (org: string) => ["copilot-approvals", org] as const,
  preview: (org: string, id: string) => ["copilot-approval-preview", org, id] as const,
  jobs: (org: string) => ["copilot-jobs", org] as const,
  routines: (org: string) => ["copilot-routines", org] as const,
  runs: (org: string, id: string) => ["copilot-routine-runs", org, id] as const,
};

function actionsBase(realm: Realm): string {
  return realm === "admin" ? "/v1/admin/copilot/actions" : "/v1/copilot/actions";
}

/** The activity log, newest first. */
export function useCopilotActivity(session: Session, realm: Realm) {
  return useQuery<CopilotActionPageOut>({
    queryKey: key.actions(realm, session.orgSlug),
    queryFn: () =>
      apiRequest<CopilotActionPageOut>(session, `${actionsBase(realm)}?limit=${ACTIVITY_PAGE}`),
    refetchInterval: WORKSPACE_POLL_MS,
  });
}

/** An older page of the activity log, read on demand. */
export function fetchOlderActivity(
  session: Session,
  realm: Realm,
  before: string,
): Promise<CopilotActionPageOut> {
  const query = new URLSearchParams({ limit: String(ACTIVITY_PAGE), before });
  return apiRequest<CopilotActionPageOut>(session, `${actionsBase(realm)}?${query}`);
}

/** The Approvals inbox. */
export function useCopilotApprovals(session: Session, enabled = true) {
  return useQuery<CopilotActionPageOut>({
    queryKey: key.approvals(session.orgSlug),
    queryFn: () => apiRequest<CopilotActionPageOut>(session, "/v1/copilot/approvals"),
    refetchInterval: WORKSPACE_POLL_MS,
    enabled,
  });
}

/** What approving one waiting action would do, read fresh when the person opens it. */
export function useApprovalPreview(session: Session, actionId: string | null) {
  return useQuery<CopilotApprovalPreviewOut>({
    queryKey: key.preview(session.orgSlug, actionId ?? ""),
    queryFn: () =>
      apiRequest<CopilotApprovalPreviewOut>(
        session,
        `/v1/copilot/approvals/${encodeURIComponent(actionId ?? "")}/preview`,
      ),
    enabled: actionId !== null,
    // Always fresh: a preview is a reading of the world NOW, and a cached one from ten
    // minutes ago is exactly the stale picture approving is meant to avoid.
    staleTime: 0,
  });
}

function useInvalidateWorkspace(session: Session) {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: key.approvals(session.orgSlug) });
    void client.invalidateQueries({ queryKey: key.actions("client", session.orgSlug) });
    void client.invalidateQueries({ queryKey: key.jobs(session.orgSlug) });
  };
}

/**
 * Approve one waiting action: it runs now, after a fresh check. Not retried — the second
 * post of an approval that landed is answered "already decided", a refusal about our own
 * retry (`useConfirmProposal`'s reason).
 */
export function useApproveAction(session: Session) {
  const client = useQueryClient();
  const invalidate = useInvalidateWorkspace(session);
  return useMutation<CopilotConfirmOut, unknown, string>({
    mutationFn: (actionId) =>
      apiRequest<CopilotConfirmOut>(
        session,
        `/v1/copilot/approvals/${encodeURIComponent(actionId)}/approve`,
        { method: "POST" },
      ),
    onSuccess: (result) => {
      invalidate();
      if (result.applied) refreshAfterConfirm(client, session.orgSlug, result.tool);
    },
  });
}

export function useRejectAction(session: Session) {
  const invalidate = useInvalidateWorkspace(session);
  return useMutation<CopilotActionOut, unknown, string>({
    mutationFn: (actionId) =>
      apiRequest<CopilotActionOut>(
        session,
        `/v1/copilot/approvals/${encodeURIComponent(actionId)}/reject`,
        { method: "POST" },
      ),
    onSuccess: invalidate,
  });
}

/** The person's recent background tasks. */
export function useCopilotJobs(session: Session) {
  return useQuery<CopilotJobPageOut>({
    queryKey: key.jobs(session.orgSlug),
    queryFn: () => apiRequest<CopilotJobPageOut>(session, "/v1/copilot/jobs"),
    refetchInterval: (query) =>
      query.state.data?.jobs.some((job) => job.status === "queued" || job.status === "running")
        ? 3_000
        : WORKSPACE_POLL_MS,
  });
}

export function useCancelJob(session: Session) {
  const invalidate = useInvalidateWorkspace(session);
  return useMutation<CopilotJobOut, unknown, string>({
    mutationFn: (jobId) =>
      apiRequest<CopilotJobOut>(session, `/v1/copilot/jobs/${encodeURIComponent(jobId)}/cancel`, {
        method: "POST",
      }),
    onSuccess: invalidate,
  });
}

export function useRoutines(session: Session) {
  return useQuery<CopilotRoutinePageOut>({
    queryKey: key.routines(session.orgSlug),
    queryFn: () => apiRequest<CopilotRoutinePageOut>(session, "/v1/copilot/routines"),
    refetchInterval: WORKSPACE_POLL_MS,
  });
}

function useInvalidateRoutines(session: Session) {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: key.routines(session.orgSlug) });
    void client.invalidateQueries({ queryKey: ["copilot-routine-runs", session.orgSlug] });
    void client.invalidateQueries({ queryKey: key.jobs(session.orgSlug) });
  };
}

export function useCreateRoutine(session: Session) {
  const invalidate = useInvalidateRoutines(session);
  return useMutation<CopilotRoutineOut, unknown, CopilotRoutineIn>({
    mutationFn: (body) =>
      apiRequest<CopilotRoutineOut>(session, "/v1/copilot/routines", { method: "POST", body }),
    onSuccess: invalidate,
  });
}

export function useUpdateRoutine(session: Session) {
  const invalidate = useInvalidateRoutines(session);
  return useMutation<CopilotRoutineOut, unknown, { id: string; patch: CopilotRoutinePatch }>({
    mutationFn: ({ id, patch }) =>
      apiRequest<CopilotRoutineOut>(session, `/v1/copilot/routines/${encodeURIComponent(id)}`, {
        method: "PATCH",
        body: patch,
      }),
    onSuccess: invalidate,
  });
}

export function useDeleteRoutine(session: Session) {
  const invalidate = useInvalidateRoutines(session);
  return useMutation<unknown, unknown, string>({
    mutationFn: (id) =>
      apiRequest<unknown>(session, `/v1/copilot/routines/${encodeURIComponent(id)}`, {
        method: "DELETE",
      }),
    onSuccess: invalidate,
  });
}

export function useRunRoutine(session: Session) {
  const invalidate = useInvalidateRoutines(session);
  return useMutation<CopilotRoutineRunOut, unknown, string>({
    mutationFn: (id) =>
      apiRequest<CopilotRoutineRunOut>(
        session,
        `/v1/copilot/routines/${encodeURIComponent(id)}/run`,
        { method: "POST" },
      ),
    onSuccess: invalidate,
  });
}

export function useRoutineRuns(session: Session, routineId: string | null) {
  return useQuery<CopilotRoutineRunPageOut>({
    queryKey: key.runs(session.orgSlug, routineId ?? ""),
    queryFn: () =>
      apiRequest<CopilotRoutineRunPageOut>(
        session,
        `/v1/copilot/routines/${encodeURIComponent(routineId ?? "")}/runs`,
      ),
    enabled: routineId !== null,
  });
}

// --- words ------------------------------------------------------------------------------

export const WEEKDAYS: readonly { value: Weekday; short: string; long: string }[] = [
  { value: "mon", short: "Mon", long: "Monday" },
  { value: "tue", short: "Tue", long: "Tuesday" },
  { value: "wed", short: "Wed", long: "Wednesday" },
  { value: "thu", short: "Thu", long: "Thursday" },
  { value: "fri", short: "Fri", long: "Friday" },
  { value: "sat", short: "Sat", long: "Saturday" },
  { value: "sun", short: "Sun", long: "Sunday" },
];

const WEEKDAY_SET: readonly Weekday[] = ["mon", "tue", "wed", "thu", "fri"];

/** "Every day at 9:00 am", "Weekdays at 6:30 pm", "Mon, Thu at 10:00 am". */
export function scheduleWords(schedule: { days: readonly Weekday[]; time: string }): string {
  const days = WEEKDAYS.filter((day) => schedule.days.includes(day.value));
  const when =
    days.length === 7
      ? "Every day"
      : days.length === 5 && WEEKDAY_SET.every((day) => schedule.days.includes(day))
        ? "Weekdays"
        : days.length === 2 && schedule.days.includes("sat") && schedule.days.includes("sun")
          ? "Weekends"
          : days.length === 1
            ? `Every ${days[0].long}`
            : days.map((day) => day.short).join(", ");
  return `${when} at ${clockWords(schedule.time)}`;
}

/** "09:00" → "9:00 am"; "18:30" → "6:30 pm". India reads a 12-hour clock. */
export function clockWords(time: string): string {
  const [hours, minutes] = time.split(":").map((part) => Number.parseInt(part, 10));
  if (!Number.isFinite(hours) || !Number.isFinite(minutes)) return time;
  const suffix = hours < 12 ? "am" : "pm";
  const twelve = hours % 12 === 0 ? 12 : hours % 12;
  return `${twelve}:${String(minutes).padStart(2, "0")} ${suffix}`;
}
