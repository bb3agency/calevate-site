"use client";

/**
 * Client-realm knowledge hooks.
 *
 * Only the submitting half lives in the client realm — approval and publish are admin
 * actions (D-22), which is why there is no `approve` mutation here and why the screen
 * says a submission is "in review" rather than showing a button that would 403.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import { queryKeys } from "./hooks";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type KbSource = Schemas["SourceOut"];
export type KbChunk = Schemas["ChunkOut"];
export type KbSubmitResult = Schemas["SubmitOut"];

export function useKbSources(session: Session): UseQueryResult<KbSource[]> {
  return useQuery({
    queryKey: ["kb", session.orgSlug],
    queryFn: () => apiRequest<KbSource[]>(session, "/v1/kb/sources"),
    // Slower than the call surfaces: an approval is a human on our side, measured in
    // hours, not the two-minute post-call SLO.
    refetchInterval: 120_000,
  });
}

export function useKbChunks(session: Session, sourceId: string | null) {
  return useQuery({
    queryKey: ["kb-preview", session.orgSlug, sourceId],
    queryFn: () => apiRequest<KbChunk[]>(session, `/v1/kb/sources/${sourceId}/preview`),
    enabled: Boolean(sourceId),
  });
}

export function useSubmitKnowledge(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ agentId, name, body }: { agentId: string; name: string; body: string }) =>
      apiRequest<KbSubmitResult>(session, "/v1/kb/sources", {
        method: "POST",
        body: { agent_id: agentId, name, body, kind: "text" },
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["kb", session.orgSlug] }),
  });
}

export type StaffCuration = Schemas["StaffCurationOut"];

/**
 * May this account's `staff` members curate knowledge — the owner's own switch.
 *
 * READ ON `org:read`, which every role holds, so a staff member sees WHY the form is
 * closed to them rather than only that it is. Writing it is `org:manage`, so the control
 * is rendered disabled for anyone but an owner (and for a view-as operator, D-22).
 */
export function useStaffCuration(session: Session): UseQueryResult<StaffCuration> {
  return useQuery({
    queryKey: ["kb-staff-curation", session.orgSlug],
    queryFn: () => apiRequest<StaffCuration>(session, "/v1/kb/staff-curation"),
  });
}

export function useSetStaffCuration(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (enabled: boolean) =>
      apiRequest<StaffCuration>(session, "/v1/kb/staff-curation", {
        method: "PUT",
        body: { staff_may_curate_knowledge: enabled },
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["kb-staff-curation", session.orgSlug] });
      // `/v1/me` reports the EFFECTIVE permission set and `kb:write` is now part of it for
      // an eligible staff member (apps/api/tenancy/routes.py::me), so flipping this switch
      // changes what `useWriteAccess` will say. Without this invalidation an owner who
      // turns it on watches nothing happen until the next reload — and, worse, a staff
      // member left on the screen keeps a disabled form the server would now accept.
      //
      // `queryKeys.me(...)` rather than the literal `["me", slug]`, for the reason the
      // `useAgents` note at the bottom of this file records: two spellings of one key that
      // happen to be equal today is exactly how an invalidation silently stops working.
      void client.invalidateQueries({ queryKey: queryKeys.me(session.orgSlug) });
    },
  });
}

/*
 * `useAgents` deliberately does NOT live here.
 *
 * It existed twice — once here and once in `agents.ts` — fetching the same
 * `/v1/agents` with two separately-written cache keys that happened to be equal
 * (`["agents", org]` vs `agentKeys.all(org)`). `publishing.ts` invalidates the literal
 * `["agents", slug]` after an Apply, so the knowledge and campaigns screens refreshed
 * only by that coincidence: change either spelling and two of the four callers would
 * have gone on showing a stale agent list with nothing to indicate it. Import it from
 * `@/lib/api/agents`, which owns the key registry.
 */
