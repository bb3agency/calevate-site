"use client";

/**
 * A campaign's or inbound line's saved script versions (D-1039):
 * `GET .../script/versions`, and what "Put back the flow from before Pip" restores.
 *
 * Every save of the script is a version, with who wrote it. Put-back restores the owner's own
 * last version, never the script as it stood before an automatic pass; a restore is itself a
 * version, so it can be undone from the list. The restore mutations live with their holder
 * (`campaignWorkspace.ts`, `inboundLines.ts`) so the holder's cache takes the server's copy.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];
export type ScriptVersions = Schemas["ScriptVersionsOut"];
export type ScriptVersion = Schemas["ScriptVersionOut"];
export type ScriptAuthor = ScriptVersion["author"];

/** One restore: a version by id, or the owner's own last one (`versionId` absent). */
export type ScriptRestore = {
  versionId?: string;
  /** `current_version_id` as the page read it; a save since then refuses the restore. */
  expectedVersionId: string | null;
  /** Which version comes back, for the dialog and the toast: "your version from 23 Nov,
   * 04:10 pm". Not sent. */
  label: string;
};

export type ScriptHolder = { kind: "campaign" | "line"; id: string };

const holderPath = ({ kind, id }: ScriptHolder) =>
  `${kind === "campaign" ? "/v1/campaigns" : "/v1/inbound-lines"}/${encodeURIComponent(id)}/script`;

/** The restore's route and body, shared by both holders' mutations. */
export function restoreRequest(holder: ScriptHolder, input: ScriptRestore) {
  const path = input.versionId
    ? `${holderPath(holder)}/versions/${encodeURIComponent(input.versionId)}/restore`
    : `${holderPath(holder)}/restore-before-pip`;
  return { path, body: { expected_version_id: input.expectedVersionId } };
}

/**
 * Keyed on the script as the page shows it, so any save (the owner's, Pip's, a restore)
 * reads the versions again without each writer having to know this query exists.
 */
export function useScriptVersions(
  session: Session,
  holder: ScriptHolder,
  shownScript: unknown,
  enabled = true,
): UseQueryResult<ScriptVersions> {
  return useQuery({
    queryKey: ["script-versions", session.orgSlug, holder.kind, holder.id, stamp(shownScript)],
    queryFn: () => apiRequest<ScriptVersions>(session, `${holderPath(holder)}/versions`),
    enabled,
  });
}

/** A short, stable digest of the shown script for the query key (not a security hash). */
function stamp(value: unknown): string {
  const text = JSON.stringify(value ?? null);
  let hash = 0;
  for (let i = 0; i < text.length; i += 1) hash = (Math.imul(hash, 31) + text.charCodeAt(i)) | 0;
  return `${text.length}:${hash}`;
}

/** Who wrote a version, in the owner's words. */
export const AUTHOR_LABELS: Record<ScriptAuthor, string> = {
  owner: "You",
  pip_draft: "Pip, when you asked",
  pip_repair: "Pip, fixing mistakes",
  pip_outcomes: "Pip, step outcomes",
  pip_notices: "Pip, call notices",
  system: "Automatic update",
  restored: "You, putting one back",
  copied: "Copied",
  earlier: "Before versions",
};
