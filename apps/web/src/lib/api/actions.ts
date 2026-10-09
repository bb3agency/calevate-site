"use client";

/**
 * In-call ACTIONS — the Actions area of an agent and the account's Connections.
 *
 * Every type here comes off the generated `schema.d.ts`, never a hand-written mirror, so a
 * server change to the tool or credential shape surfaces as a `tsc` error rather than a
 * runtime surprise (the same doctrine as `integrations.ts` and `whatsappAlerts.ts`).
 *
 * The master switch and the per-tool `enabled` are the SERVER's state, and a change reaches
 * a live agent at once (D-700): this module does not try to recompute "is it live".
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
export type ConnectOut = Schemas["ConnectOut"];
export type ConnectionsStatus = Schemas["ConnectionsStatusOut"];
export type CredentialTest = Schemas["CredentialTestOut"];
export type ActionRun = Schemas["InvocationOut"];

/** The accounts a client connects by signing in to them, not by pasting a key. */
export type OAuthKind = "google_calendar" | "google_sheets" | "zoho_crm" | "hubspot";
export type SheetsPicker = Schemas["SheetsPickerOut"];

/** A short-lived token and key for Google's file picker on the owner's own connection. */
export function openSheetsPicker(session: Session, credentialId: string): Promise<SheetsPicker> {
  return apiRequest<SheetsPicker>(
    session,
    `/v1/integrations/google-sheets/${encodeURIComponent(credentialId)}/picker`,
    { method: "POST" },
  );
}

export const actionKeys = {
  agent: (org: string, agentId: string) => ["actions", org, agentId] as const,
  credentials: (org: string) => ["actions", "credentials", org] as const,
  connections: (org: string) => ["actions", "connections", org] as const,
  log: (org: string, agentId: string, toolId: string) =>
    ["actions", org, agentId, "log", toolId] as const,
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

/** Connected accounts and saved keys — fingerprints only, never the secret. */
export function useCredentials(session: Session): UseQueryResult<IntegrationCredential[]> {
  return useQuery({
    queryKey: actionKeys.credentials(session.orgSlug),
    queryFn: () => apiRequest<IntegrationCredential[]>(session, CREDS_PATH),
  });
}

/** Which sign-in connections this deployment can offer, and where a sheet is shared. */
export function useConnectionsStatus(session: Session): UseQueryResult<ConnectionsStatus> {
  return useQuery({
    queryKey: actionKeys.connections(session.orgSlug),
    queryFn: () =>
      apiRequest<ConnectionsStatus>(session, "/v1/integrations/connections/status"),
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

/**
 * Disconnect an account. Every action using it leaves the live agents at once and, if a
 * caller still reaches one, the agent says it cannot do that right now.
 */
export function useDeleteCredential(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (credentialId: string) =>
      apiRequest<void>(session, `${CREDS_PATH}/${encodeURIComponent(credentialId)}`, {
        method: "DELETE",
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["actions"] }),
  });
}

/** Prove a connection works without sending anything to anyone. */
export function useTestCredential(session: Session) {
  return useMutation({
    mutationFn: (credentialId: string) =>
      apiRequest<CredentialTest>(
        session,
        `${CREDS_PATH}/${encodeURIComponent(credentialId)}/test`,
        { method: "POST" },
      ),
  });
}

/** Begin a sign-in connection — answers the consent page to open in a popup. */
export function useOAuthConnect(session: Session) {
  return useMutation({
    mutationFn: (kind: OAuthKind) =>
      apiRequest<ConnectOut>(session, `/v1/integrations/oauth/${kind}/connect`, {
        method: "GET",
      }),
  });
}

/** Finish a sign-in connection with what the provider handed back to our callback page. */
export function useOAuthComplete(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      kind,
      code,
      state,
      accountsServer,
    }: {
      kind: OAuthKind;
      code: string;
      state: string;
      accountsServer: string | null;
    }) =>
      apiRequest<IntegrationCredential>(session, `/v1/integrations/oauth/${kind}/callback`, {
        method: "POST",
        body: { code, state, accounts_server: accountsServer },
      }),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: actionKeys.credentials(session.orgSlug) }),
  });
}

/** Turn the whole feature on or off for one agent. Live calls follow at once. */
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
 * Run an action once with sample values. It executes the REAL external call — a WhatsApp
 * test really sends, a booking really books — so the screen must say so. A WhatsApp or
 * payment-link test goes only to one of the business's own numbers (`testPhone`).
 */
export function useTestAction(session: Session, agentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      toolId,
      values,
      testPhone,
    }: {
      toolId: string;
      values: Record<string, unknown>;
      testPhone: string | null;
    }) =>
      apiRequest<TestResult>(session, `${agentPath(agentId)}/${encodeURIComponent(toolId)}/test`, {
        method: "POST",
        body: { values, test_phone: testPhone },
      }),
    onSuccess: (_result, { toolId }) =>
      void client.invalidateQueries({
        queryKey: actionKeys.log(session.orgSlug, agentId, toolId),
      }),
  });
}

/** The most recent runs of one action: when, from where, and the outcome. */
export function useActionLog(
  session: Session,
  agentId: string,
  toolId: string,
  enabled: boolean,
): UseQueryResult<ActionRun[]> {
  return useQuery({
    queryKey: actionKeys.log(session.orgSlug, agentId, toolId),
    queryFn: () =>
      apiRequest<ActionRun[]>(
        session,
        `${agentPath(agentId)}/${encodeURIComponent(toolId)}/log`,
      ),
    enabled,
  });
}

export const ACTION_KIND_LABELS: Record<string, string> = {
  custom_api: "Your own API",
  whatsapp: "WhatsApp message",
  calendar: "Google Calendar",
  sheets: "Google Sheets",
  payment_link: "Payment link",
  crm: "CRM record",
  caller_lookup: "Know the caller",
};

export const PROVIDER_LABELS: Record<string, string> = {
  aisensy: "AiSensy",
  meta_cloud: "WhatsApp Cloud API",
  interakt: "Interakt",
  custom: "Other (your own API)",
  google: "Google Calendar",
  google_calendar: "Google Calendar",
  google_sheets: "Google Sheets",
  zoho: "Zoho CRM",
  zoho_crm: "Zoho CRM",
  hubspot: "HubSpot",
  razorpay: "Razorpay",
  sheet: "Google Sheet",
  api: "Your own API",
  custom_api: "Your own API key",
};

/** What an outcome code means, in the client's words, for the run log and test results. */
export const RUN_STATUS_LABELS: Record<string, string> = {
  delivered: "Message sent",
  link_sent: "Payment link sent",
  booked: "Booked",
  checked: "Checked the calendar",
  found: "Found",
  not_found: "Not found",
  row_added: "Row added",
  row_updated: "Row updated",
  crm_saved: "Saved to CRM",
  no_credential: "Account not connected",
  credential_unusable: "Account needs reconnecting",
  auth_failed: "Account refused the connection",
  not_opted_in: "Caller has not agreed to WhatsApp",
  blocked: "Number may not be contacted",
  slot_taken: "Slot already taken",
  timeout: "Took too long",
  sheet_not_shared: "Sheet not chosen for Calevate",
  trial_payment_links: "Not on a free trial",
  amount_outside_rules: "Amount outside your limits",
};

export const RUN_SOURCE_LABELS: Record<string, string> = {
  in_call: "On a call",
  background: "After the agent moved on",
  after_call: "After the call",
  test: "Test",
};
