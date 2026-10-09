"use client";

/**
 * The client's side of the auto-healer: problems with their lines, the phone callers are
 * passed to, and the changes suggested for a struggling agent.
 *
 * Every sentence a client reads about a problem comes from the server
 * (`apps/api/healer/notices.py`), the same sentences the email and the dashboard notice
 * carry, so the three can never disagree. Nothing here composes copy about an incident.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type LineIncidents = Schemas["ClientIncidentsOut"];
export type LineIncident = Schemas["ClientIncidentOut"];
export type FallbackPhone = Schemas["FallbackPhoneOut"];
export type HealerProposals = Schemas["ProposalsOut"];
export type HealerProposal = Schemas["ProposalOut"];

export const LINE_INCIDENTS_PATH = "/v1/healer/incidents";
export const FALLBACK_PHONE_PATH = "/v1/healer/fallback-phone";
export const HEALER_PROPOSALS_PATH = "/v1/healer/proposals";

export const healerKeys = {
  incidents: (org: string) => ["healer", "incidents", org] as const,
  fallback: (org: string) => ["healer", "fallback-phone", org] as const,
  proposals: (org: string) => ["healer", "proposals", org] as const,
};

/** Indian mobile, the only shape the server accepts for a fallback phone. */
export const INDIA_MOBILE = /^\+91[6-9]\d{9}$/;

/** "98765 43210" or "+91 98765-43210" → "+919876543210"; anything else unchanged. */
export function normaliseIndianMobile(raw: string): string {
  const digits = raw.replace(/[^\d+]/g, "");
  if (/^[6-9]\d{9}$/.test(digits)) return `+91${digits}`;
  if (/^91[6-9]\d{9}$/.test(digits)) return `+${digits}`;
  return digits;
}

export function useLineIncidents(session: Session): UseQueryResult<LineIncidents> {
  return useQuery({
    queryKey: healerKeys.incidents(session.orgSlug),
    queryFn: () => apiRequest<LineIncidents>(session, `${LINE_INCIDENTS_PATH}?days=30&limit=20`),
  });
}

export function useRestoreLine(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (incidentId: string) =>
      apiRequest<LineIncident>(
        session,
        `${LINE_INCIDENTS_PATH}/${encodeURIComponent(incidentId)}/restore`,
        { method: "POST" },
      ),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: healerKeys.incidents(session.orgSlug) }),
  });
}

export function useFallbackPhone(session: Session): UseQueryResult<FallbackPhone> {
  return useQuery({
    queryKey: healerKeys.fallback(session.orgSlug),
    queryFn: () => apiRequest<FallbackPhone>(session, FALLBACK_PHONE_PATH),
  });
}

export function useSetFallbackPhone(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (phone: string | null) =>
      phone === null
        ? apiRequest<FallbackPhone>(session, FALLBACK_PHONE_PATH, { method: "DELETE" })
        : apiRequest<FallbackPhone>(session, FALLBACK_PHONE_PATH, {
            method: "PUT",
            body: { phone_e164: phone },
          }),
    onSuccess: (data) => client.setQueryData(healerKeys.fallback(session.orgSlug), data),
  });
}

export function useHealerProposals(session: Session): UseQueryResult<HealerProposals> {
  return useQuery({
    queryKey: healerKeys.proposals(session.orgSlug),
    queryFn: () =>
      apiRequest<HealerProposals>(session, `${HEALER_PROPOSALS_PATH}?days=30&limit=20`),
  });
}

export function useDecideProposal(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: "apply" | "dismiss" }) =>
      apiRequest<HealerProposal>(
        session,
        `${HEALER_PROPOSALS_PATH}/${encodeURIComponent(id)}/${decision}`,
        { method: "POST" },
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: healerKeys.proposals(session.orgSlug) });
      void client.invalidateQueries({ queryKey: healerKeys.incidents(session.orgSlug) });
    },
  });
}
