"use client";

/**
 * A client's plan for calling new leads, and the leads held for release (D-716).
 *
 * One plan per client, not per agent. The server returns the rules no client can switch
 * off (`always_applied`) and the trial sentence, so the screen states them in the server's
 * words rather than its own.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type LeadCalling = Schemas["LeadCallingOut"];
export type LeadCallingInput = Schemas["LeadCallingIn"];
export type HeldLead = Schemas["HeldLeadOut"];
export type HeldLeads = Schemas["HeldLeadsOut"];
export type Released = Schemas["ReleasedOut"];

const planKey = (session: Session) => ["lead-calling", session.orgSlug];
const heldKey = (session: Session) => ["lead-calling", "held", session.orgSlug];

export function useLeadCalling(session: Session) {
  return useQuery({
    queryKey: planKey(session),
    queryFn: () => apiRequest<LeadCalling>(session, "/v1/lead-calling"),
  });
}

export function useSaveLeadCalling(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: LeadCallingInput) =>
      apiRequest<LeadCalling>(session, "/v1/lead-calling", { method: "PUT", body: input }),
    onSuccess: (saved) => client.setQueryData(planKey(session), saved),
  });
}

export function useHeldLeads(session: Session) {
  return useQuery({
    queryKey: heldKey(session),
    queryFn: () => apiRequest<HeldLeads>(session, "/v1/lead-calling/held"),
    refetchInterval: 60_000,
  });
}

function useHeldAction(session: Session, leaf: "release" | "drop") {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (holdId: string) =>
      apiRequest<Released | null>(session, `/v1/lead-calling/held/${holdId}/${leaf}`, {
        method: "POST",
      }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: heldKey(session) });
      void client.invalidateQueries({ queryKey: planKey(session) });
    },
  });
}

export function useReleaseHeldLead(session: Session) {
  return useHeldAction(session, "release");
}

export function useDropHeldLead(session: Session) {
  return useHeldAction(session, "drop");
}
