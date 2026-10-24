"use client";

/**
 * ONE ACCOUNT'S CALL HANDLING DEFAULTS as editable rows: the pause before replying, hanging up
 * when finished, what agents do when the caller goes quiet, the lines said while looking
 * something up, and a background sound. "Calevate default" saves `null`.
 *
 * Shared by the owner's screen (`/c/[slug]/settings/call-handling`) and the operator's
 * (`/admin/tenants/[tenantId]/call-handling`); each passes its own read and its own write,
 * because the two reach the server through different doors.
 */

import { useState } from "react";
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
  pauseLabel,
  platformVoice,
  type OrganizationCallHandling,
  type OrganizationCallHandlingIn,
} from "@/lib/api/callHandling";

type Row = "pause" | "hang-up" | "silence" | "filler" | "sound";

export function CallHandlingDefaultsRows({
  data,
  save,
  status,
  canChange,
  idPrefix = "organization",
  ownLabel = "Your organisation default",
}: {
  data: OrganizationCallHandling;
  save: UseMutationResult<OrganizationCallHandling, Error, OrganizationCallHandlingIn>;
  /** The caller's `useActionFeedback(save).status`, shown on the row that saved. */
  status: FeedbackStatus;
  canChange: boolean;
  idPrefix?: string;
  /** The hint on a row this account set itself, in the reader's words. */
  ownLabel?: string;
}) {
  // Which row the last save came from, so its busy state and refusal show on that row.
  const [row, setRow] = useState<Row | null>(null);

  // The pause and the hang-up are always stated; the row's own fields ride beside them, and
  // the server keeps every field the body leaves out.
  const send = (
    which: Row,
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
  const rowStatus = (which: Row): FeedbackStatus => (row === which ? status : "idle");
  const error = (which: Row) => (row === which ? save.error : null);

  return (
    <SettingRows className="border-y border-line">
      <PauseRow
        idPrefix={idPrefix}
        effective={data.turn_silence_ms_effective}
        source={data.turn_silence_ms === null ? "platform" : "organization"}
        sourceHint={ownOrOurs(ownLabel, data.turn_silence_ms)}
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
        sourceHint={ownOrOurs(ownLabel, data.end_call_on_finish)}
        own={data.end_call_on_finish}
        inheritLabel={`Calevate default: ${data.bounds.platform_end_call_on_finish ? "On" : "Off"}`}
        canChange={canChange}
        status={rowStatus("hang-up")}
        error={error("hang-up")}
        onSave={(next, done) => send("hang-up", { end_call_on_finish: next }, done)}
      />
      <SilenceRow
        idPrefix={idPrefix}
        hint={ownOrOurs(
          ownLabel,
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
        hint={ownOrOurs(ownLabel, data.filler_lines)}
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
        hint={ownOrOurs(ownLabel, data.ambience, data.ambience_volume_pct)}
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
  );
}

/** The organisation level: its own choice, or Calevate's. */
function ownOrOurs(ownLabel: string, ...values: readonly unknown[]): string {
  return values.some((value) => value !== null) ? ownLabel : "Calevate default";
}
