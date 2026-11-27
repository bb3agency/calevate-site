"use client";

/**
 * The checks on a campaign's or an inbound line's SAVED script (script rebuild §3.4):
 * `GET /v1/campaigns/{id}/script/checks` and `GET /v1/inbound-lines/{id}/script/checks`.
 * A `block` finding stops Put it live and Start (problem code `script_needs_fix`); a `warn`
 * never stops anything. Save and Keep are never refused on a check.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import type { LineWarning } from "@/app/c/[slug]/agents/[agentId]/script/stepExamples";

import { ApiProblem, apiRequest, type Session } from "./client";
import type { components } from "./schema";

export type ScriptChecks = components["schemas"]["ScriptChecksOut"];
export type ScriptFinding = components["schemas"]["ScriptCheckOut"];

/** The refusal's problem code, and the launch checklist's rule for the same refusal. */
export const SCRIPT_NEEDS_FIX = "script_needs_fix";

export type ScriptHolder = { kind: "campaign" | "line"; id: string };

export function isScriptNeedsFix(error: unknown): boolean {
  return error instanceof ApiProblem && error.code === SCRIPT_NEEDS_FIX;
}

/** A script longer than calls can take (`engine_limits.PROMPT_TOO_LONG`); never cured by a retry. */
export const PROMPT_TOO_LONG = "engine_prompt_too_long";

export function isPromptTooLong(error: unknown): error is ApiProblem {
  return error instanceof ApiProblem && error.code === PROMPT_TOO_LONG;
}

const path = (holder: ScriptHolder) =>
  holder.kind === "campaign"
    ? `/v1/campaigns/${encodeURIComponent(holder.id)}/script/checks`
    : `/v1/inbound-lines/${encodeURIComponent(holder.id)}/script/checks`;

export const scriptChecksKey = (org: string, holder: ScriptHolder, saved: string) =>
  ["script-checks", org, holder.kind, holder.id, saved] as const;

/** A short stand-in for the saved script in the query key, so a new save reads its checks again. */
export function savedMark(script: unknown): string {
  const text = JSON.stringify(script ?? null);
  let hash = 0;
  for (let i = 0; i < text.length; i += 1) hash = (hash * 31 + text.charCodeAt(i)) | 0;
  return `${text.length}:${hash}`;
}

/** The saved script's findings. `script` is the saved script, read only for the key. */
export function useScriptChecks(
  session: Session,
  holder: ScriptHolder | null,
  script: unknown,
): UseQueryResult<ScriptChecks, Error> {
  return useQuery({
    queryKey: scriptChecksKey(session.orgSlug, holder ?? { kind: "line", id: "" }, savedMark(script)),
    queryFn: () => apiRequest<ScriptChecks>(session, path(holder as ScriptHolder)),
    enabled: holder !== null && script != null,
  });
}

/**
 * The findings as the editors place them: the path keyed by the step's id rather than its
 * place in the list (`stages.2.…` to `stages.<id>.…`), so a finding stays on its step while
 * the owner reorders, and the line it was about, so an edit that changes it settles it.
 */
export function findingWarnings(findings: readonly ScriptFinding[]): LineWarning[] {
  return findings.map((f) => {
    const parts = f.path.split(".");
    const keyed = parts[0] === "stages" && f.stage_id && /^\d+$/.test(parts[1] ?? "")
      ? ["stages", f.stage_id, ...parts.slice(2)].join(".")
      : f.path;
    const { short, rest } = splitDetail(f.detail || f.message);
    return {
      path: keyed,
      message: short,
      detail: rest || null,
      text: f.line ? f.line : null,
      severity: f.severity,
    };
  });
}

/** The first clause on the line; the rest behind "Why?". */
function splitDetail(detail: string): { short: string; rest: string } {
  const text = detail.trim();
  const upper = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);
  const cut = text.search(/[;.](\s|$)/);
  if (cut < 0 || cut >= text.length - 1) return { short: upper(text), rest: "" };
  const short = text.slice(0, cut + 1).replace(/;$/, ".");
  return { short: upper(short), rest: text.slice(cut + 1).trim() };
}

/** What "Let Pip fix it" asks: those lines fixed, everything else kept. Within the ask's 4000. */
export function fixLinesAsk(findings: readonly ScriptFinding[]): string {
  const lines = findings
    .filter((f) => f.severity === "block")
    .map((f) => `- ${f.message}`);
  let ask = "Fix only these lines in the script, and keep everything else as it is:";
  for (const line of lines) {
    if (ask.length + line.length + 1 > 3900) break;
    ask += `\n${line}`;
  }
  return ask;
}

/** "Show me": the page scrolls to the first flagged line, opening its step where it can. */
export const SHOW_FINDING_EVENT = "calevate:show-script-finding";

export function showFinding(stageId: string | null): void {
  window.dispatchEvent(new CustomEvent(SHOW_FINDING_EVENT, { detail: { stageId } }));
}

/** Scroll the first flagged line on the page into view and put the focus near it. */
export function scrollToFirstFinding(): void {
  window.requestAnimationFrame(() =>
    window.requestAnimationFrame(() => {
      const first = document.querySelector<HTMLElement>("[data-script-finding]");
      first?.scrollIntoView?.({ block: "center" });
      const field = first?.closest("div")?.querySelector<HTMLElement>("textarea, input");
      field?.focus({ preventScroll: true });
    }),
  );
}
