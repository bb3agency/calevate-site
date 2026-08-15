"use client";

/**
 * Platform configuration — the admin realm's view of `/v1/ops/config`
 * (PLATFORM-CONFIG §7, §8 panel 2).
 *
 * THE TRAP THIS FILE WAS WRITTEN AROUND. A Pydantic field with a default is OPTIONAL in
 * the generated TypeScript, so `editable` would arrive as `boolean | undefined` and the
 * console would have to write `field.editable ?? true` — whose fallback for "we do not
 * know" is "offer the form". Every field the console must trust therefore carries NO
 * default on the API side, and the generated types confirm it: none of them is optional.
 * If one ever comes back optional, the fix is on the API, not a `??` here.
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
import { ApiProblem, apiRequest } from "./client";

import type { components } from "./schema";

type Schemas = components["schemas"];

export const OPS_CONFIG_PATH = "/v1/ops/config";
export const OPS_CONFIG_QUERY_KEY = ["admin", "ops", "config"] as const;

/** A managed setting's value on the wire. Money is a STRING (`"88.50"`), never a
 *  number — hard rule 7 does not stop at the database. */
export type ConfigValue = string | boolean | number | null;

/** Where the value in force came from. `env` cannot be changed from here. */
export type ConfigSource = "env" | "db" | "default";

/** How to render an editor. Derived server-side from the field's own annotation. */
export type ConfigKind = "string" | "integer" | "number" | "boolean" | "enum" | "decimal";

/**
 * When a change takes effect, as `applies` spells the two answers the API has TODAY.
 *
 * Documentation, deliberately not a narrowing of `ConfigField["applies"]`, which is
 * `string` on the wire. The same call D-75 records for `events`: this union is what THIS
 * BUILD has words for, and the server's value is what the RUNNING DEPLOYMENT sends. A
 * key labelled `on_republish` by a newer API must reach the screen as an unrecognised
 * word it can say so about, not as a response-validation failure — `appliesVerdict` in
 * ConfigPanel.tsx is where that fourth answer is rendered.
 */
export type ConfigApplies = "live" | "on_restart";

/** One managed setting: its value, where that value came from, and whether it may be changed here. */
export type ConfigField = ConfigFieldWire;

/**
 * Every managed setting, plus the snapshot's own health.
 *
 * `config_changed_at` is what makes `config_version` legible: a version bumped four
 * seconds ago and one bumped four days ago mean different things when a change is not
 * appearing. Both come from the DATABASE's sentinel, never from the reader's clock.
 */
export type ConfigList = Schemas["ConfigOut"];

/** The answer to a write: what it was, what it is, and the version that now carries it. */
export type ConfigWrite = ConfigWriteWire;

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

/* ══════════════════════════════════════════════════════════════════════════════════════
 * TEMPORARY — HAND-DECLARED WIRE FIELDS. Delete this fence after `pnpm gen:api`.
 *
 * `apps/api/ops/config_routes.py` grew three fields this slice needs and
 * `src/lib/api/schema.d.ts` has not been regenerated (that file is off-limits here):
 *
 *   ConfigFieldOut.etag: str        — the key's concurrency token, `"0"` for no row
 *   ConfigWriteOut.etag: str        — the token AFTER the write
 *   ConfigWriteOut.recorded: bool   — False when the value was already the stored one
 *
 * TO RESTORE, exactly:
 *   1. run `pnpm -C apps/web gen:api`;
 *   2. delete this block down to the `END HAND-DECLARED` fence;
 *   3. replace `ConfigFieldWire` / `ConfigWriteWire` in the two type aliases below with
 *      `Schemas["ConfigFieldOut"]` / `Schemas["ConfigWriteOut"]`;
 *   4. run `pnpm -C apps/web typecheck test`.
 *
 * EVERY ADDED FIELD IS OPTIONAL HERE, and that is the trap this repo has hit four times,
 * avoided: a Pydantic field with a default is OPTIONAL in the generated TypeScript, so a
 * hand-written `required` breaks on the swap. None of these three carries a default
 * today, so the swap will widen them to required and nothing here will break — but
 * declaring them required and being wrong is the failure that costs a session, and
 * declaring them optional and being conservative costs one branch each. Both branches
 * are live code with a stated meaning, not `?? true`:
 *
 *   - no `etag` ⇒ this API cannot be written to conditionally, and it REQUIRES a
 *     conditional write (428 without `If-Match`), so the console refuses to offer a form
 *     rather than sending a request that can only fail;
 *   - no `recorded` ⇒ the write happened, which is what an API without the field means.
 * ══════════════════════════════════════════════════════════════════════════════════════ */

type ConfigFieldWire = Schemas["ConfigFieldOut"] & { etag?: string };
type ConfigWriteWire = Schemas["ConfigWriteOut"] & { etag?: string; recorded?: boolean };

/* ══ END HAND-DECLARED ══════════════════════════════════════════════════════════════ */

/**
 * A conditional write was refused because the token had moved.
 *
 * 412, and only 412 — `_refuse_stale` in `apps/api/ops/config_service.py` chose it over
 * 409 deliberately (RFC 9110 §15.5.13: "one or more conditions given in the request
 * header fields evaluated to false"), and this reads the status rather than the code so
 * a rename on either side cannot quietly turn the conflict screen off.
 *
 * FAIL DIRECTION IS DELIBERATE. Anything else answers `false` and renders the server's
 * own words through `ProblemNotice`, which leaves the save blocked. The two neighbours
 * matter: 428 `config_if_match_required` is THIS CLIENT failing to send a precondition —
 * a bug here, not a peer — and 409 `config_key_set_in_environment` is a key that cannot
 * be stored at all. Offering "keep mine and replace theirs" for either would be a
 * control with no possible outcome.
 */
export function isLostUpdate(error: unknown): boolean {
  return error instanceof ApiProblem && error.status === 412;
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
  /**
   * The entity-tag this edit was decided against, verbatim from the read that showed it.
   *
   * REQUIRED, because the API requires it: `require_if_match` answers 428 without one
   * (RFC 6585), deliberately, so that the runbook curl and the second console get the
   * same protection as this form rather than "a losing write is refused" being a property
   * of one client. Optional here would mean a console that can silently send an
   * unconditional write, which is the property the server just removed.
   */
  ifMatch: string;
}

export function useSetConfig() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ key, value, reason, ifMatch }: ConfigSetInput) =>
      apiRequest<ConfigWrite>(adminSession(), `${OPS_CONFIG_PATH}/${key}`, {
        method: "PUT",
        body: { value, reason },
        confirmAction: configConfirmation(key),
        ifMatch,
      }),
    // Re-read rather than patching the cache with the response. The write changes what
    // the SERVING PROCESS reports for other keys too — the config version moves, and
    // `stale` can flip — and a console that spliced one field into a list it already
    // held would show a fresh row inside a stale page.
    onSuccess: () => void client.invalidateQueries({ queryKey: OPS_CONFIG_QUERY_KEY }),
    // A REFUSED write re-reads too, and that is the point of the branch rather than
    // tidiness: the screen's next job is to say what the value is NOW, and the only
    // authority for that is the server. Scoped to a lost update — a validation refusal
    // changed nothing, and refetching on every failed save would make a wrong keystroke
    // look like a state change.
    onError: (error: Error) => {
      if (isLostUpdate(error)) void client.invalidateQueries({ queryKey: OPS_CONFIG_QUERY_KEY });
    },
  });
}

export interface ConfigRevertInput {
  key: string;
  /** Reverting is conditional too — arguably more so; see `clear_value`'s docstring. */
  ifMatch: string;
}

export function useRevertConfig() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ key, ifMatch }: ConfigRevertInput) =>
      apiRequest<ConfigWrite>(adminSession(), `${OPS_CONFIG_PATH}/${key}`, {
        method: "DELETE",
        confirmAction: revertConfirmation(key),
        ifMatch,
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: OPS_CONFIG_QUERY_KEY }),
    onError: (error: Error) => {
      if (isLostUpdate(error)) void client.invalidateQueries({ queryKey: OPS_CONFIG_QUERY_KEY });
    },
  });
}
