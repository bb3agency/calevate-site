"use client";

/**
 * ONE ACCOUNT'S CALL HANDLING DEFAULTS as editable rows: the pause before replying, hanging up
 * when finished, what agents do when the caller goes quiet, the lines said while looking
 * something up, and a background sound. "Calevate default" saves `null`.
 *
 * Shared by the owner's screen (`/c/[slug]/settings/call-handling`) and the operator's
 * (`/admin/tenants/[tenantId]/call-handling`); each passes its own read and its own write,
 * because the two reach the server through different doors.
 *
 * Under each row's source go the agents that set their own value for it, with that value and
 * a link to the agent. A default reaches only the agents that follow it; without the list this
 * screen said "Background sound: Off" about an account whose one agent plays an office.
 */

import Link from "next/link";
import { useState, type ReactNode } from "react";
import type { UseMutationResult } from "@tanstack/react-query";

import { type FeedbackStatus } from "@/components/arc/feedback";
import { HangUpRow, PauseRow } from "@/components/callHandlingRows";
import {
  BackgroundSoundRow,
  FillerLinesRow,
  SilenceRow,
} from "@/components/callHandlingVoiceRows";
import { SettingRows } from "@/components/console/settingRow";
import {
  agentOverrides,
  pauseLabel,
  platformVoice,
  type AgentOverride,
  type DefaultsRow,
  type OrganizationCallHandling,
  type OrganizationCallHandlingIn,
} from "@/lib/api/callHandling";

/** Agents named under one row before the rest are counted. */
const NAMED_PER_ROW = 3;

const AGENT_LINK =
  "rounded-sm font-medium text-brand-strong underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand dark:text-brand-bright touch:py-3.5";

export function CallHandlingDefaultsRows({
  data,
  save,
  status,
  canChange,
  agentHref,
  idPrefix = "organization",
  ownLabel = "Your organisation default",
}: {
  data: OrganizationCallHandling;
  save: UseMutationResult<OrganizationCallHandling, Error, OrganizationCallHandlingIn>;
  /** The caller's `useActionFeedback(save).status`, shown on the row that saved. */
  status: FeedbackStatus;
  canChange: boolean;
  /** Where this reader opens one agent's call handling. */
  agentHref: (agentId: string) => string;
  idPrefix?: string;
  /** The hint on a row this account set itself, in the reader's words. */
  ownLabel?: string;
}) {
  // Which row the last save came from, so its busy state and refusal show on that row.
  const [row, setRow] = useState<DefaultsRow | null>(null);
  const overrides = agentOverrides(data);
  const unlisted = data.agents_with_own_total - data.agents_with_own.length;

  // The pause and the hang-up are always stated; the row's own fields ride beside them, and
  // the server keeps every field the body leaves out.
  const send = (
    which: DefaultsRow,
    fields: Partial<OrganizationCallHandlingIn>,
    done: () => void,
  ) => {
    setRow(which);
    save.mutate(
      {
        turn_silence_ms: data.turn_silence_ms,
        end_call_on_finish: data.end_call_on_finish,
        ...fields,
      },
      { onSuccess: done },
    );
  };
  const rowStatus = (which: DefaultsRow): FeedbackStatus => (row === which ? status : "idle");
  const error = (which: DefaultsRow) => (row === which ? save.error : null);
  const hint = (which: DefaultsRow, ...values: readonly unknown[]): ReactNode => (
    <>
      {ownOrOurs(ownLabel, ...values)}
      <AgentsWithOwn agents={overrides[which]} agentHref={agentHref} />
    </>
  );

  return (
    <div className="space-y-2">
      <SettingRows className="border-y border-line">
        <PauseRow
          idPrefix={idPrefix}
          effective={data.turn_silence_ms_effective}
          source={data.turn_silence_ms === null ? "platform" : "organization"}
          sourceHint={hint("pause", data.turn_silence_ms)}
          own={data.turn_silence_ms}
          inheritLabel={`Calevate default: ${pauseLabel(data.bounds.platform_turn_silence_ms)}`}
          minMs={data.bounds.turn_silence_min_ms}
          maxMs={data.bounds.turn_silence_max_ms}
          canChange={canChange}
          status={rowStatus("pause")}
          error={error("pause")}
          onSave={(next, done) => send("pause", { turn_silence_ms: next }, done)}
        />
        <HangUpRow
          idPrefix={idPrefix}
          effective={data.end_call_on_finish_effective}
          source={data.end_call_on_finish === null ? "platform" : "organization"}
          sourceHint={hint("hang-up", data.end_call_on_finish)}
          own={data.end_call_on_finish}
          inheritLabel={`Calevate default: ${data.bounds.platform_end_call_on_finish ? "On" : "Off"}`}
          canChange={canChange}
          status={rowStatus("hang-up")}
          error={error("hang-up")}
          onSave={(next, done) => send("hang-up", { end_call_on_finish: next }, done)}
        />
        <SilenceRow
          idPrefix={idPrefix}
          hint={hint(
            "silence",
            data.nudge_after_seconds,
            data.nudge_count,
            data.nudge_phrase,
            data.end_after_silence_seconds,
          )}
          bounds={data.bounds}
          inherited={platformVoice(data.bounds)}
          canChange={canChange}
          status={rowStatus("silence")}
          error={error("silence")}
          own={{
            nudge_after_seconds: data.nudge_after_seconds,
            nudge_count: data.nudge_count,
            nudge_phrase: data.nudge_phrase,
            end_after_silence_seconds: data.end_after_silence_seconds,
          }}
          effective={{
            nudge_after_seconds: data.nudge_after_seconds_effective,
            nudge_count: data.nudge_count_effective,
            nudge_phrase: data.nudge_phrase_effective,
            end_after_silence_seconds: data.end_after_silence_seconds_effective,
          }}
          onSave={(next, done) => send("silence", next, done)}
        />
        <FillerLinesRow
          idPrefix={idPrefix}
          hint={hint("filler", data.filler_lines)}
          bounds={data.bounds}
          inherited={platformVoice(data.bounds)}
          canChange={canChange}
          status={rowStatus("filler")}
          error={error("filler")}
          own={data.filler_lines}
          effective={data.filler_lines_effective}
          onSave={(next, done) => send("filler", { filler_lines: next }, done)}
        />
        <BackgroundSoundRow
          idPrefix={idPrefix}
          hint={hint("sound", data.ambience, data.ambience_volume_pct)}
          bounds={data.bounds}
          inherited={platformVoice(data.bounds)}
          canChange={canChange}
          status={rowStatus("sound")}
          error={error("sound")}
          own={{ ambience: data.ambience, ambience_volume_pct: data.ambience_volume_pct }}
          effective={{
            ambience: data.ambience_effective,
            ambience_volume_pct: data.ambience_volume_pct_effective,
          }}
          onSave={(next, done) => send("sound", next, done)}
        />
      </SettingRows>
      {unlisted > 0 && (
        <p className="text-meta text-ink-muted">
          {unlisted === 1 ? "1 more agent has" : `${unlisted} more agents have`} settings of their
          own that are not listed here. Open each agent to see them.
        </p>
      )}
    </div>
  );
}

/** The organisation level: its own choice, or Calevate's. */
function ownOrOurs(ownLabel: string, ...values: readonly unknown[]): string {
  return values.some((value) => value !== null) ? ownLabel : "Calevate default";
}

/** "Anjali uses its own: Office at 15%", one line per agent, each name a link to it. */
function AgentsWithOwn({
  agents,
  agentHref,
}: {
  agents: readonly AgentOverride[];
  agentHref: (agentId: string) => string;
}) {
  if (agents.length === 0) return null;
  const named = agents.slice(0, NAMED_PER_ROW);
  const rest = agents.length - named.length;
  return (
    <>
      {named.map((agent) => (
        <span key={agent.agentId} className="mt-0.5 block [overflow-wrap:anywhere]">
          <Link href={agentHref(agent.agentId)} className={AGENT_LINK}>
            {agent.name}
          </Link>{" "}
          uses its own: {agent.value}
        </span>
      ))}
      {rest > 0 && (
        <span className="mt-0.5 block">
          and {rest === 1 ? "1 more agent" : `${rest} more agents`} with their own
        </span>
      )}
    </>
  );
}
