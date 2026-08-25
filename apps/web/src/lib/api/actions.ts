"use client";

/**
 * In-call ACTIONS — the Actions tab client (custom API, WhatsApp, calendar).
 *
 * Every type here comes off the generated `schema.d.ts`, never a hand-written mirror, so a
 * server change to the tool or credential shape surfaces as a `tsc` error rather than a
 * runtime surprise (the same doctrine as `integrations.ts` and `whatsappAlerts.ts`).
 *
 * The master switch and the per-tool `enabled` are the SERVER's state; a change reaches
 * live calls at the next agent publish (the "Apply to live calls" action), exactly as a
 * voice or cap change does — this module does not try to recompute "is it live".
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type ActionsSettings = Schemas["ActionsSettingsOut"];
export type ActionTool = Schemas["ToolOut"];
export type ActionToolInput = Schemas["ToolIn"];
export type ActionParam = Schemas["ParamIn"];
export type IntegrationCredential = Schemas["CredentialOut"];
export type NewCredential = Schemas["CreateCredentialIn"];
export type TestResult = Schemas["TestActionOut"];
export type CalendarConnect = Schemas["CalendarConnectOut"];

export const actionKeys = {
  agent: (org: string, agentId: string) => ["actions", org, agentId] as const,
  credentials: (org: string) => ["actions", "credentials", org] as const,
};

const agentPath = (agentId: string) => `/v1/agents/${encodeURIComponent(agentId)}/actions`;
const CREDS_PATH = "/v1/integrations/credentials";

/** The master switch + every configured tool + whether calendar can be offered. `org:read`. */
export function useAgentActions(session: Session, agentId: string): UseQueryResult<ActionsSettings> {
  return useQuery({
    queryKey: actionKeys.agent(session.orgSlug, agentId),
    queryFn: () => apiRequest<ActionsSettings>(session, agentPath(agentId)),
  });
}

/** Saved, reusable integration credentials — fingerprints only, never the secret. */
export function useCredentials(session: Session): UseQueryResult<IntegrationCredential[]> {
  return useQuery({
    queryKey: actionKeys.credentials(session.orgSlug),
    queryFn: () => apiRequest<IntegrationCredential[]>(session, CREDS_PATH),
  });
}

export function useCreateCredential(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: NewCredential) =>
      apiRequest<IntegrationCredential>(session, CREDS_PATH, { method: "POST", body }),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: actionKeys.credentials(session.orgSlug) }),
  });
}

export function useDeleteCredential(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (credentialId: string) =>
      apiRequest<void>(session, `${CREDS_PATH}/${encodeURIComponent(credentialId)}`, {
        method: "DELETE",
      }),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: actionKeys.credentials(session.orgSlug) }),
  });
}

/** Turn the whole feature on or off for one agent. Applies to live calls at next publish. */
export function useSetMasterSwitch(session: Session, agentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (enabled: boolean) =>
      apiRequest<ActionsSettings>(session, `${agentPath(agentId)}/enabled`, {
        method: "PUT",
        body: { enabled },
      }),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: actionKeys.agent(session.orgSlug, agentId) }),
  });
}

export function useCreateAction(session: Session, agentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ActionToolInput) =>
      apiRequest<ActionTool>(session, agentPath(agentId), { method: "POST", body }),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: actionKeys.agent(session.orgSlug, agentId) }),
  });
}

export function useUpdateAction(session: Session, agentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ toolId, body }: { toolId: string; body: ActionToolInput }) =>
      apiRequest<ActionTool>(session, `${agentPath(agentId)}/${encodeURIComponent(toolId)}`, {
        method: "PUT",
        body,
      }),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: actionKeys.agent(session.orgSlug, agentId) }),
  });
}

export function useSetActionEnabled(session: Session, agentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ toolId, enabled }: { toolId: string; enabled: boolean }) =>
      apiRequest<ActionTool>(
        session,
        `${agentPath(agentId)}/${encodeURIComponent(toolId)}/enabled`,
        { method: "PUT", body: { enabled } },
      ),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: actionKeys.agent(session.orgSlug, agentId) }),
  });
}

export function useDeleteAction(session: Session, agentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (toolId: string) =>
      apiRequest<void>(session, `${agentPath(agentId)}/${encodeURIComponent(toolId)}`, {
        method: "DELETE",
      }),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: actionKeys.agent(session.orgSlug, agentId) }),
  });
}

/**
 * Run an action with sample values before it goes live (the "Test API" tab). It executes
 * the REAL external call — a WhatsApp test really sends, a booking really books — so the
 * screen must say so. Not invalidated: a test changes no stored state.
 */
export function useTestAction(session: Session, agentId: string) {
  return useMutation({
    mutationFn: ({ toolId, values }: { toolId: string; values: Record<string, unknown> }) =>
      apiRequest<TestResult>(session, `${agentPath(agentId)}/${encodeURIComponent(toolId)}/test`, {
        method: "POST",
        body: { values },
      }),
  });
}

/** Begin Google Calendar OAuth — returns the consent URL to send the client to. */
export function useCalendarConnect(session: Session) {
  return useMutation({
    mutationFn: () =>
      apiRequest<CalendarConnect>(session, "/v1/actions/calendar/connect", { method: "GET" }),
  });
}

export const ACTION_KIND_LABELS: Record<string, string> = {
  custom_api: "Custom API",
  whatsapp: "WhatsApp",
  calendar: "Google Calendar",
};

export const PROVIDER_LABELS: Record<string, string> = {
  aisensy: "AiSensy",
  meta_cloud: "Meta Cloud API",
  interakt: "Interakt",
  custom: "Other (Custom API)",
  google: "Google Calendar",
};
