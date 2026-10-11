"use client";

/**
 * THE ACCOUNT'S CALL HANDLING DEFAULTS (D-751): the pause before an agent replies and
 * whether it hangs up when it has finished, for every agent that has not been given its own
 * on its Call handling section. "Calevate default" saves `null`, so the account follows ours.
 *
 * NO `<h1>`: the app shell renders the page title from the nav list it also renders.
 */

import { useState } from "react";

import { HangUpRow, PauseRow } from "@/components/callHandlingRows";
import { PageHeader } from "@/components/console/pageHeader";
import { SettingRows } from "@/components/console/settingRow";
import { ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import {
  formatPause,
  pauseLabel,
  useOrganizationCallHandling,
  useSetOrganizationCallHandling,
} from "@/lib/api/callHandling";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

export function CallHandlingScreen() {
  const session = useClientSession();
  const state = useOrganizationCallHandling(session);
  const save = useSetOrganizationCallHandling(session);
  const write = useWriteAccess(session, "org:manage", "change how your agents end turns and calls");

  const data = state.data;
  // Which row the last save came from, so its busy state and refusal show on that row.
  const [row, setRow] = useState<"pause" | "hang-up" | null>(null);

  useCopilotSurface({
    route: "/c/{slug}/settings/call-handling",
    title: "Call handling defaults",
    realm: "client",
    fields: [],
    facts: state.data
      ? [
          {
            key: "pause_before_reply",
            label: "Pause before agents reply, unless an agent has its own",
            value: `${pauseLabel(state.data.turn_silence_ms_effective)}${state.data.turn_silence_ms === null ? ", the Calevate default" : ""}`,
          },
          {
            key: "hang_up_when_finished",
            label: "Agents hang up when the conversation ends, unless an agent has its own",
            value: `${state.data.end_call_on_finish_effective ? "yes" : "no, finished calls stay connected and charged until the caller hangs up"}${state.data.end_call_on_finish === null ? ", the Calevate default" : ""}`,
          },
        ]
      : [
          {
            key: "state",
            label: "What is on screen",
            value: state.error ? "the settings failed to load" : "still loading",
          },
        ],
    apply: noFill,
  });

  return (
    <div className="max-w-2xl space-y-5 pb-12">
      <PageHeader description="How every agent waits for callers and ends its calls, unless one has its own." />
      {state.error != null && <ProblemNotice error={state.error} onRetry={() => void state.refetch()} />}
      {state.isLoading ? (
        <Skeleton rows={2} label="Loading your call handling defaults" />
      ) : !data ? null : (
        <>
          <RestrictionNote reason={write.allowed ? null : write.reason} />
          <SettingRows className="border-y border-line">
            <PauseRow
              idPrefix="organization"
              effective={data.turn_silence_ms_effective}
              source={data.turn_silence_ms === null ? "platform" : "organization"}
              own={data.turn_silence_ms}
              inheritLabel={`Calevate default (${formatPause(data.bounds.platform_turn_silence_ms)})`}
              minMs={data.bounds.turn_silence_min_ms}
              maxMs={data.bounds.turn_silence_max_ms}
              canChange={write.allowed}
              saving={save.isPending && row === "pause"}
              error={row === "pause" ? save.error : null}
              onSave={(next, done) => {
                setRow("pause");
                save.mutate(
                  { turn_silence_ms: next, end_call_on_finish: data.end_call_on_finish },
                  { onSuccess: done },
                );
              }}
            />
            <HangUpRow
              idPrefix="organization"
              effective={data.end_call_on_finish_effective}
              source={data.end_call_on_finish === null ? "platform" : "organization"}
              own={data.end_call_on_finish}
              inheritLabel={`Calevate default (${data.bounds.platform_end_call_on_finish ? "on" : "off"})`}
              canChange={write.allowed}
              saving={save.isPending && row === "hang-up"}
              error={row === "hang-up" ? save.error : null}
              onSave={(next, done) => {
                setRow("hang-up");
                save.mutate(
                  { turn_silence_ms: data.turn_silence_ms, end_call_on_finish: next },
                  { onSuccess: done },
                );
              }}
            />
          </SettingRows>
        </>
      )}
    </div>
  );
}
