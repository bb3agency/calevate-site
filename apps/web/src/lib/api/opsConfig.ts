"use client";

/**
 * Platform configuration — the admin realm's view of `/v1/ops/config`
 * (PLATFORM-CONFIG §7, §8 panel 2).
 *
 * ══ THE TYPES BELOW ARE TEMPORARY AND HAND-WRITTEN ══════════════════════════════════
 *
 * `schema.d.ts` is generated from the API's OpenAPI document and this slice must not
 * regenerate it (the regeneration is a separate, coordinated step). So the three
 * response shapes are transcribed here, field for field, from
 * `apps/api/ops/config_routes.py`. **When `pnpm -C apps/web gen:api` next runs, delete
 * the `ConfigField` / `ConfigList` / `ConfigWrite` interfaces below and restore these
 * three lines in their place:**
 *
 *     export type ConfigField = Schemas["ConfigFieldOut"];
 *     export type ConfigList = Schemas["ConfigOut"];
 *     export type ConfigWrite = Schemas["ConfigWriteOut"];
 *
 * (with `import type { components } from "./schema";` and
 * `type Schemas = components["schemas"];` at the top, as every other module here does).
 * Nothing else in this file changes: the hooks, the paths and the confirmation strings
 * are written against these names.
 *
 * THE TRAP THAT MADE THIS WORTH SPELLING OUT. A Pydantic field with a default is
 * OPTIONAL in the generated TypeScript, so `editable` would arrive as `boolean |
 * undefined` and the console would have to write `field.editable ?? true` — whose
 * fallback for "we do not know" is "offer the form". Every field the console must trust
 * therefore carries NO default on the API side and is required here. If the generated
 * types come back with any of these optional, the fix is on the API, not a `??` here.
 *
 * ══ WHAT THIS MODULE REFUSES TO DO ══════════════════════════════════════════════════
 *
 * It never decides whether a key is editable, what its source is, or what reverting
 * would restore. All three come from the server, which computes them from the same
 * resolution the running process uses — a console that re-derived them would eventually
 * offer a form for a key the environment is pinning, which is §8's named defect ("a
 * field that silently does nothing is worse than no field").
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";

export const OPS_CONFIG_PATH = "/v1/ops/config";
export const OPS_CONFIG_QUERY_KEY = ["admin", "ops", "config"] as const;

/** A managed setting's value on the wire. Money is a STRING (`"88.50"`), never a
 *  number — hard rule 7 does not stop at the database. */
export type ConfigValue = string | boolean | number | null;

/** Where the value in force came from. `env` cannot be changed from here. */
export type ConfigSource = "env" | "db" | "default";

/** How to render an editor. Derived server-side from the field's own annotation. */
export type ConfigKind = "string" | "integer" | "number" | "boolean" | "enum" | "decimal";

/** When a change takes effect. */
export type ConfigApplies = "live" | "on_restart";

/** TEMPORARY — see the header. Mirrors `ConfigFieldOut`. */
export interface ConfigField {
  key: string;
  env_var: string;
  value: ConfigValue;
  source: ConfigSource;
  default: ConfigValue;
  has_default: boolean;
  kind: ConfigKind;
  options: string[];
  editable: boolean;
  applies: ConfigApplies;
  caveat: string | null;
  updated_by: string | null;
  updated_at: string | null;
  note: string | null;
}

/** TEMPORARY — see the header. Mirrors `ConfigOut`. */
export interface ConfigList {
  fields: ConfigField[];
  config_version: number;
  stale: boolean;
  never_loaded: boolean;
  /** When the configuration last changed, from the DATABASE's sentinel — which is what
   *  makes `config_version` legible: a version bumped four seconds ago and one bumped
   *  four days ago mean different things when a change is not appearing. */
  config_changed_at: string | null;
}

/** TEMPORARY — see the header. Mirrors `ConfigWriteOut`. */
export interface ConfigWrite {
  key: string;
  previous: ConfigValue;
  field: ConfigField;
  config_version: number;
}

/**
 * The step-up strings, copied from `apps/api/ops/config_routes.py` VERBATIM.
 *
 * Two of them rather than one, because the API binds them separately and says why:
 * setting a value and putting the code default back are different acts, and a header
 * captured for either must not authorise the other. Copied rather than derived from a
 * shared constant, for the reason `useSetTmRegistration` copies its direction rule —
 * this is a property of the request the console is sending, and a mismatch is REFUSED
 * by the server rather than assumed.
 */
export function configConfirmation(key: string): string {
  return `set_config:${key}`;
}

export function revertConfirmation(key: string): string {
  return `revert_config:${key}`;
}

export function useOpsConfig(): UseQueryResult<ConfigList> {
  return useQuery({
    queryKey: OPS_CONFIG_QUERY_KEY,
    queryFn: () => apiRequest<ConfigList>(adminSession(), OPS_CONFIG_PATH),
    // Slower than the ops screen's 30s platform poll on purpose: configuration changes
    // are deliberate acts by a person at a keyboard, not a state that drifts underneath
    // one. A tighter poll would clobber a half-typed form more often than it would tell
    // anyone anything.
    refetchInterval: 60_000,
  });
}

export interface ConfigSetInput {
  key: string;
  value: ConfigValue;
  reason: string;
}

export function useSetConfig() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ key, value, reason }: ConfigSetInput) =>
      apiRequest<ConfigWrite>(adminSession(), `${OPS_CONFIG_PATH}/${key}`, {
        method: "PUT",
        body: { value, reason },
        confirmAction: configConfirmation(key),
      }),
    // Re-read rather than patching the cache with the response. The write changes what
    // the SERVING PROCESS reports for other keys too — the config version moves, and
    // `stale` can flip — and a console that spliced one field into a list it already
    // held would show a fresh row inside a stale page.
    onSuccess: () => void client.invalidateQueries({ queryKey: OPS_CONFIG_QUERY_KEY }),
  });
}

export function useRevertConfig() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (key: string) =>
      apiRequest<ConfigWrite>(adminSession(), `${OPS_CONFIG_PATH}/${key}`, {
        method: "DELETE",
        confirmAction: revertConfirmation(key),
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: OPS_CONFIG_QUERY_KEY }),
  });
}
