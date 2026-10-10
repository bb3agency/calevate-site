"use client";

/**
 * SCRIPT — what the agent does on a call, summarised, and the way into the builder.
 *
 * The builder is its own route because it is a working surface (a canvas, a list, an
 * editor beside them). This section says what is there and whether callers hear it yet,
 * from the same read the builder uses. No version numbers: an owner needs "live" or
 * "changes waiting", and History in the builder lists entries by date.
 */

import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { PRIMARY_BUTTON, ProblemNotice, SECONDARY_BUTTON, Skeleton } from "@/components/ui";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import type { Agent } from "@/lib/api/agents";
import { useScript, type ScriptOut } from "@/lib/api/script";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { hasUnpublished, workingCopy } from "../script/scriptDraft";

/** Whether callers hear the script, in plain words. */
export function liveScriptText(agent: Pick<Agent, "published">, out: ScriptOut): string {
  const waiting = hasUnpublished(out, workingCopy(out).script);
  if (out.version === null) return waiting ? "Not put live yet" : "Not written yet";
  if (!agent.published) return waiting ? "Changes waiting · agent is off" : "Ready · agent is off";
  return waiting ? "Live, with changes waiting" : "Live";
}

export function ScriptSection({ agent, slug }: { agent: Agent; slug: string }) {
  const { href } = useClientRealm();
  const session = useClientSession();
  const script = useScript(session, agent.id);
  const builder = href(`/c/${slug}/agents/${agent.id}/script`);
  const data = script.data;
  const working = data ? workingCopy(data).script : null;
  const count = working?.stages?.length ?? 0;
  const handWritten = working?.raw_override !== null && working !== null;

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
      ...(data && working
        ? [
            { key: "live", label: "Whether callers hear it", value: liveScriptText(agent, data) },
            { key: "opening_line", label: "Opening line", value: handWritten ? "written by hand" : working.opening_line },
            { key: "sections", label: "Sections", value: String(count) },
          ]
        : []),
      { key: "builder", label: "Where the script is edited", value: "the script builder (Open the script)" },
    ],
    apply: noFill,
  });

  return (
    <div className="max-w-2xl space-y-5">
      <p className="max-w-prose text-body text-ink-muted">
        The script decides what the agent says and how the call goes. Your changes save as a
        draft; callers hear them only after you put them live.
      </p>

      {script.error && <ProblemNotice error={script.error} onRetry={() => void script.refetch()} />}
      {script.isLoading ? (
        <Skeleton rows={3} />
      ) : data && working ? (
        <SettingRows>
          <SettingRow label="Callers hear it" value={liveScriptText(agent, data)} />
          <SettingRow
            label="Opening line"
            value={handWritten ? "Written by hand" : working.opening_line.trim() || "Not written yet"}
          />
          {!handWritten && (
            <SettingRow label="Sections" value={`${count} ${count === 1 ? "section" : "sections"}`} />
          )}
        </SettingRows>
      ) : null}

      <div className="flex flex-wrap gap-2">
        <Link href={builder} className={PRIMARY_BUTTON}>
          Open the script
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
