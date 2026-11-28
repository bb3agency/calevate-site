"use client";

/**
 * API keys and the API activity log (D-1047). Types come off the generated `schema.d.ts`,
 * so a server shape change is a `tsc` error here rather than a surprise in the browser.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { accountAction, withAccountCode } from "@/lib/api/accountCode";
import { apiRequest, type Session } from "@/lib/api/client";
import { untilRefused } from "@/lib/api/queryRetry";
import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];
export type ApiKey = Schemas["ApiKeyOut"];
export type ApiKeys = Schemas["ApiKeysOut"];
export type NewApiKey = Schemas["CreateApiKeyIn"];
export type CreatedApiKey = Schemas["CreatedApiKeyOut"];
export type ApiActivity = Schemas["ApiActivityOut"];

const PATH = "/v1/api-keys";

export const apiKeyKeys = {
  all: (org: string) => ["api-keys", org] as const,
  activity: (org: string, keyId: string | null, failed: boolean) =>
    ["api-keys", org, "activity", keyId ?? "all", failed] as const,
};

export function useApiKeys(session: Session): UseQueryResult<ApiKeys> {
  return useQuery({
    queryKey: apiKeyKeys.all(session.orgSlug),
    queryFn: () => apiRequest<ApiKeys>(session, PATH),
  });
}

export function useApiActivity(
  session: Session,
  keyId: string | null,
  failed: boolean,
): UseQueryResult<{ requests: ApiActivity[] }> {
  const query = new URLSearchParams();
  if (keyId) query.set("key_id", keyId);
  if (failed) query.set("failed", "true");
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return useQuery({
    queryKey: apiKeyKeys.activity(session.orgSlug, keyId, failed),
    queryFn: () => apiRequest<{ requests: ApiActivity[] }>(session, `${PATH}/activity${suffix}`),
    refetchInterval: untilRefused(30_000),
  });
}

/** Make a key. A code is typed for it (D-730); the answer holds the key once. */
export function useCreateApiKey(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: NewApiKey) => {
      const confirmAction = accountAction(session, "create_api_key");
      return withAccountCode(confirmAction, "Making a key that can act for your account.", () =>
        apiRequest<CreatedApiKey>(session, PATH, { method: "POST", body, confirmAction }),
      );
    },
    onSuccess: () => void client.invalidateQueries({ queryKey: apiKeyKeys.all(session.orgSlug) }),
  });
}

function useKeyAction(session: Session, verb: "revoke" | "renew") {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (keyId: string) =>
      apiRequest<ApiKey>(session, `${PATH}/${encodeURIComponent(keyId)}/${verb}`, {
        method: "POST",
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: apiKeyKeys.all(session.orgSlug) }),
  });
}

export function useRevokeApiKey(session: Session) {
  return useKeyAction(session, "revoke");
}

export function useRenewApiKey(session: Session) {
  return useKeyAction(session, "renew");
}
