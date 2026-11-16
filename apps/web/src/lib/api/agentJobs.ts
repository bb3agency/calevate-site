"use client";

/**
 * An agent's jobs (founder, 16 Nov 2026): the Inbound lines and open campaigns that speak in
 * its voice, from `GET /v1/agents/{id}/jobs`. The agent has no script of its own, so its
 * work, and each job's own test call, is reached from here.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

export type AgentJobs = components["schemas"]["AgentJobsOut"];
export type AgentJob = components["schemas"]["AgentJobOut"];

/** The fold on an Inbound line's page that holds its test call. */
export const LINE_TEST_ANCHOR = "line-test-call";
/** The fold on a draft campaign's page that holds its test call. */
export const CAMPAIGN_TEST_ANCHOR = "campaign-test";

export const agentJobsKey = (org: string, agentId: string) => ["agent-jobs", org, agentId] as const;

export function useAgentJobs(session: Session, agentId: string): UseQueryResult<AgentJobs> {
  return useQuery({
    queryKey: agentJobsKey(session.orgSlug, agentId),
    queryFn: () => apiRequest<AgentJobs>(session, `/v1/agents/${agentId}/jobs`),
  });
}

/**
 * Where a job's own test call is: an Inbound line's Test call fold, or a draft campaign's.
 * A campaign that has started shows its results instead, so its page is opened at the top.
 */
export function jobTestPath(slug: string, job: AgentJob): string {
  if (job.kind === "inbound_line") return `/c/${slug}/inbound/${job.id}#${LINE_TEST_ANCHOR}`;
  return job.status === "draft"
    ? `/c/${slug}/campaigns/${job.id}#${CAMPAIGN_TEST_ANCHOR}`
    : `/c/${slug}/campaigns/${job.id}`;
}
