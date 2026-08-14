"use client";

/**
 * Credentials and key management — `/v1/ops/secrets` (PLATFORM-CONFIG §7, §8 panels 3-4).
 *
 * ══ THE TYPES BELOW ARE TEMPORARY AND HAND-WRITTEN ══════════════════════════════════
 *
 * Same situation and same fix as `opsConfig.ts`: this slice must not regenerate
 * `schema.d.ts`. **When `pnpm -C apps/web gen:api` next runs, delete the five interfaces
 * below and restore these lines in their place:**
 *
 *     export type PlatformSecret = Schemas["SecretOut"];
 *     export type SecretsList = Schemas["SecretsOut"];
 *     export type SecretTest = Schemas["SecretTestOut"];
 *     export type KekState = Schemas["KekOut"];
 *     export type RewrapResult = Schemas["RewrapOut"];
 *
 * (with `import type { components } from "./schema";` and
 * `type Schemas = components["schemas"];` at the top). Nothing else changes.
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

export const OPS_SECRETS_PATH = "/v1/ops/secrets";
export const OPS_SECRETS_QUERY_KEY = ["admin", "ops", "secrets"] as const;
export const OPS_KEK_QUERY_KEY = ["admin", "ops", "kek"] as const;

/** What `/test` concluded. `no_probe` and `unreachable` are NOT failures — they mean we
 *  could not check, which is a different sentence from "the vendor said no". */
export type ProbeOutcome = "accepted" | "rejected" | "unreachable" | "no_probe";

/** TEMPORARY — see the header. Mirrors `SecretOut`. */
export interface PlatformSecret {
  key: string;
  env_var: string;
  installed: boolean;
  version: number;
  versions: number;
  last_four: string;
  kek_id: number;
  created_at: string | null;
  created_by: string | null;
  shadowed_by_env: boolean;
  testable: boolean;
}

/** TEMPORARY — see the header. Mirrors `SecretsOut`. */
export interface SecretsList {
  secrets: PlatformSecret[];
}

/** TEMPORARY — see the header. Mirrors `SecretTestOut`. */
export interface SecretTest {
  key: string;
  outcome: ProbeOutcome;
  status: number | null;
  detail: string;
  verified: boolean;
  candidate_last_four: string;
}

/** TEMPORARY — see the header. Mirrors `KekOut`. */
export interface KekState {
  active_kek_id: number;
  has_retired_kek: boolean;
  versions: number;
  current: number;
  pending: number;
}

/** TEMPORARY — see the header. Mirrors `RewrapOut`. */
export interface RewrapResult {
  examined: number;
  rewrapped: number;
  unreadable: string[];
  active_kek_id: number;
}

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
