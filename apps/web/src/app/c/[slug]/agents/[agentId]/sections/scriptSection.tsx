"use client";

/**
 * SCRIPT — what the agent says, summarised, and the way into the builder.
 *
 * The builder is its own route because it has its own unsaved state and its own Save/Apply
 * ladder (doctrine §3: split, do not hide). This section only says what is there and which
 * version callers hear, from the reads the builder itself uses.
 */

import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { PRIMARY_BUTTON, ProblemNotice, SECONDARY_BUTTON, Skeleton } from "@/components/ui";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import type { Agent } from "@/lib/api/agents";
import { usePendingChanges } from "@/lib/api/publishing";
import { useScript } from "@/lib/api/script";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { stagedScript } from "../../panels/publishing";

/**
 * Which script version callers hear, in the words the publishing panel uses. An agent that
 * was never switched on has no live version, whatever is saved; one that is switched on
 * hears the applied version, which is the saved one unless a newer one is waiting.
 */
export function liveVersionText(
  agent: Pick<Agent, "published">,
  savedVersion: number | null,
  staged: { live_version: number | null } | undefined,
): string {
  if (!agent.published) return "Not switched on yet";
  if (staged) return staged.live_version === null ? "None yet" : `Version ${staged.live_version}`;
  return savedVersion === null ? "None yet" : `Version ${savedVersion}`;
}

export function ScriptSection({ agent, slug }: { agent: Agent; slug: string }) {
  const { href } = useClientRealm();
  const session = useClientSession();
  const script = useScript(session, agent.id);
  const pending = usePendingChanges(session, agent.id);
  const builder = href(`/c/${slug}/agents/${agent.id}/script`);

  const staged = pending.data ? stagedScript(pending.data) : undefined;
  const data = script.data;

  useCopilotSurface({
    route: "/c/{slug}/agents/{id}",
    title: "Agent: script",
    realm: "client",
    fields: [],
    facts: [
      { key: "agent_id", label: "Agent id", value: agent.id },
      {
        key: "state",
        label: "What is on screen",
        value: data ? "the script summary has loaded" : script.error ? "the script failed to load" : "still loading",
      },
      ...(data
        ? [
            { key: "version", label: "Script version saved", value: data.version === null ? "no script yet" : String(data.version) },
            { key: "opening_line", label: "Opening line", value: data.is_freeform ? "written as free text" : data.script.opening_line },
            { key: "waiting", label: "A version waiting to be applied", value: staged ? `version ${staged.staged_version}` : "none" },
          ]
        : []),
      { key: "builder", label: "Where the script is edited", value: "the script builder (Open the script builder)" },
    ],
    apply: noFill,
  });

  return (
    <div className="max-w-2xl space-y-5">
      <p className="max-w-prose text-body text-ink-muted">
        The script decides what the agent says and how it handles a call. A change never
        reaches a live call until you apply it.
      </p>

      {script.error && <ProblemNotice error={script.error} onRetry={() => void script.refetch()} />}
      {script.isLoading ? (
        <Skeleton rows={3} />
      ) : data ? (
        <SettingRows>
          <SettingRow label="Live version" value={liveVersionText(agent, data.version, staged)} />
          {staged && (
            <SettingRow label="Waiting to be applied" value={`Version ${staged.staged_version}`} />
          )}
          {!staged && data.version !== null && (
            <SettingRow label="Saved version" value={`Version ${data.version}`} />
          )}
          <SettingRow
            label="Opening line"
            value={
              data.is_freeform
                ? "Written as free text"
                : data.script.opening_line.trim() || "Not written yet"
            }
          />
          {!data.is_freeform && (
            <SettingRow
              label="Steps and answers"
              value={`${data.script.steps.length} ${data.script.steps.length === 1 ? "step" : "steps"} · ${data.script.faqs.length} ${data.script.faqs.length === 1 ? "answer" : "answers"}`}
            />
          )}
        </SettingRows>
      ) : null}

      <div className="flex flex-wrap gap-2">
        <Link href={builder} className={PRIMARY_BUTTON}>
          Open the script builder
          <ArrowRight aria-hidden className="h-4 w-4" />
        </Link>
        {data && data.version === null && (
          <Link href={`${builder}${builder.includes("?") ? "&" : "?"}assist=1`} className={SECONDARY_BUTTON}>
            Draft it with AI
          </Link>
        )}
      </div>
    </div>
  );
}
