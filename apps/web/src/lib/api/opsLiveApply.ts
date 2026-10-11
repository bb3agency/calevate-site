"use client";

/**
 * How far each saved setting has reached the live agents — the admin realm's view of
 * `GET /v1/ops/live-apply` (D-720). Counts arrive from the run the server recorded; this
 * module computes nothing from them.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";

import type { components } from "./schema";

type Schemas = components["schemas"];

export const OPS_LIVE_APPLY_PATH = "/v1/ops/live-apply";

/** One pass that puts a saved setting on the live agents in its scope. */
export type LiveApplyRun = Schemas["LiveApplyRunOut"];

/** The newest platform-wide passes (ops console settings), newest first. */
export function usePlatformLiveApply(): UseQueryResult<Schemas["LiveApplyRunsOut"]> {
  return useQuery({
    queryKey: ["admin", "ops", "live-apply", "platform"] as const,
    queryFn: () =>
      apiRequest<Schemas["LiveApplyRunsOut"]>(
        adminSession(),
        `${OPS_LIVE_APPLY_PATH}?scope=platform&limit=3`,
      ),
    // A pass over the fleet finishes in minutes; poll while one may be moving.
    refetchInterval: (query) =>
      query.state.data?.runs.some((run) => run.status === "pending" || run.status === "running")
        ? 5_000
        : 60_000,
  });
}

/**
 * "Applied to N of M live agents", from the server's own counts. Before the walk has counted
 * the agents (`total` null) the run is only queued.
 */
export function liveApplyLine(run: LiveApplyRun): string {
  if (run.status === "superseded") return "Replaced by a later change before it finished.";
  if (run.total === null) return "Queued: live agents are about to be updated.";
  const of = `Applied to ${run.applied} of ${run.total} live agent${run.total === 1 ? "" : "s"}`;
  const extra = [
    run.retrying > 0 ? `${run.retrying} retrying` : null,
    run.failed > 0 ? `${run.failed} failed` : null,
  ].filter(Boolean);
  return `${of}${extra.length ? ` (${extra.join(", ")})` : ""}${run.status === "done" ? "." : "…"}`;
}
