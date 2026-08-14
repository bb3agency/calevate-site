"use client";

/**
 * Credentials and key management — `/v1/ops/secrets` (PLATFORM-CONFIG §7, §8 panels 3-4).
 *
 * ══ THERE IS NO VALUE FIELD ANYWHERE IN THIS FILE ═══════════════════════════════════
 *
 * Not on a response type, not in a query cache, not in a hook's return. §7: there is no
 * read-back route and there will not be one, so there is nothing for the console to
 * hold. `last_four` is the only fragment that exists, and the server masks it entirely
 * below eight characters. A future field that carried a plaintext would have to be added
 * here deliberately, which is the point of writing these types out.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";

import type { components } from "./schema";

type Schemas = components["schemas"];

export const OPS_SECRETS_PATH = "/v1/ops/secrets";
export const OPS_SECRETS_QUERY_KEY = ["admin", "ops", "secrets"] as const;
export const OPS_KEK_QUERY_KEY = ["admin", "ops", "kek"] as const;

/** What `/test` concluded. `no_probe` and `unreachable` are NOT failures — they mean we
 *  could not check, which is a different sentence from "the vendor said no". Derived
 *  from the generated schema rather than restated, so the four cases cannot drift. */
export type ProbeOutcome = Schemas["SecretTestOut"]["outcome"];

/** One credential as the console may know it: identity, provenance and last-4 — never a value. */
export type PlatformSecret = Schemas["SecretOut"];

export type SecretsList = Schemas["SecretsOut"];

/** What `/test` concluded about a CANDIDATE value, before it was stored. */
export type SecretTest = Schemas["SecretTestOut"];

/** Key-encryption-key state: which key is active, and how many rows still wrap under an older one. */
export type KekState = Schemas["KekOut"];

export type RewrapResult = Schemas["RewrapOut"];

/** Copied VERBATIM from `apps/api/ops/secret_routes.py`, like every other confirmation
 *  in this console: it is a property of the request being sent, and a mismatch is
 *  refused by the server rather than assumed. */
export function secretConfirmation(key: string): string {
  return `set_secret:${key}`;
}

export const REWRAP_CONFIRMATION = "rewrap_platform_keks";

export function useSecrets(): UseQueryResult<SecretsList> {
  return useQuery({
    queryKey: OPS_SECRETS_QUERY_KEY,
    queryFn: () => apiRequest<SecretsList>(adminSession(), OPS_SECRETS_PATH),
    refetchInterval: 60_000,
  });
}

export function useKekState(): UseQueryResult<KekState> {
  return useQuery({
    queryKey: OPS_KEK_QUERY_KEY,
    queryFn: () => apiRequest<KekState>(adminSession(), `${OPS_SECRETS_PATH}/kek`),
    refetchInterval: 60_000,
  });
}

export interface SecretSetInput {
  key: string;
  value: string;
  reason: string;
}

export function useTestSecret() {
  return useMutation({
    mutationFn: ({ key, value }: { key: string; value: string }) =>
      apiRequest<SecretTest>(adminSession(), `${OPS_SECRETS_PATH}/${key}/test`, {
        method: "POST",
        body: { value },
      }),
    // NOTHING is invalidated: the test stores nothing, so nothing the console holds has
    // changed. Refetching here would suggest otherwise.
  });
}

export function useSetSecret() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ key, value, reason }: SecretSetInput) =>
      apiRequest<PlatformSecret>(adminSession(), `${OPS_SECRETS_PATH}/${key}`, {
        method: "PUT",
        body: { value, reason },
        confirmAction: secretConfirmation(key),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: OPS_SECRETS_QUERY_KEY });
      // The key-management panel counts DEKs per KEK, and a new version adds one under
      // the ACTIVE key — so its numbers move on every write here.
      void client.invalidateQueries({ queryKey: OPS_KEK_QUERY_KEY });
    },
  });
}

export function useRewrapKeks() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<RewrapResult>(adminSession(), `${OPS_SECRETS_PATH}/kek/rewrap`, {
        method: "POST",
        confirmAction: REWRAP_CONFIRMATION,
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: OPS_KEK_QUERY_KEY });
      void client.invalidateQueries({ queryKey: OPS_SECRETS_QUERY_KEY });
    },
  });
}
