import { forbiddenReason, isForbidden } from "@/app/admin/withheld";
import type { ConfigField, ConfigList } from "@/lib/api/opsConfig";

/**
 * The read of the platform configuration, and one field's concurrency token. How a value
 * is shown and edited lives in `configControl.ts`.
 */

/**
 * The read, as a type rather than as discipline (§52): loading is not empty, a failure is
 * not a table of defaults, and a 403 is a settled refusal rather than an outage.
 */
export type ConfigState =
  | { status: "loading" }
  | { status: "unreadable" }
  | { status: "forbidden"; said: string | null }
  | { status: "read"; config: ConfigList };

export function configState(query: {
  data: ConfigList | undefined;
  error: unknown;
  isLoading: boolean;
}): ConfigState {
  // The 403 before the generic failure: `GET /v1/ops/config` carries `platform:config`
  // exactly as the PUT does, and "we could not read it" with a retry beside it is the
  // sentence for an outage — this one is settled.
  if (isForbidden(query.error)) {
    return { status: "forbidden", said: forbiddenReason(query.error) };
  }
  // Error before data: a failed refetch leaves the previous `data` in place, and a stale
  // config table rendered as current is the same lie as an invented one.
  if (query.error) return { status: "unreadable" };
  if (query.isLoading || !query.data) return { status: "loading" };
  return { status: "read", config: query.data };
}

/**
 * This key's concurrency token, or `null` when the API did not send one.
 *
 * `null` is NOT `"0"`: `"0"` is a real token meaning "no row is stored", while an absent
 * field means an API that predates the precondition and refuses every write with 428. The
 * row offers no form at all for the second, rather than a form whose only outcome is that
 * refusal.
 */
export function etagOf(field: ConfigField): string | null {
  return typeof field.etag === "string" && field.etag.length > 0 ? field.etag : null;
}
