"use client";

/**
 * THE ACCOUNT'S CALL HANDLING DEFAULTS (D-751, F3, F9): the pause before an agent replies,
 * whether it hangs up when it has finished, what it does when the caller goes quiet, the lines
 * it says while it looks something up and a background sound, for every agent that has not been given its own
 * on its Call handling section. "Calevate default" saves `null`, so the account follows ours.
 *
 * NO `<h1>`: the app shell renders the page title from the nav list it also renders.
 */

import { useActionFeedback } from "@/components/arc/feedback";
import { CallHandlingDefaultsRows } from "@/components/callHandlingDefaults";
import { PageHeader } from "@/components/console/pageHeader";
import { ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import {
  agentOverridesSummary,
  ambienceSummary,
  fillerSummary,
  pauseLabel,
  silenceSummary,
  useOrganizationCallHandling,
  useSetOrganizationCallHandling,
} from "@/lib/api/callHandling";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

export function CallHandlingScreen() {
  const { session, href } = useClientRealm();
  const state = useOrganizationCallHandling(session);
  const save = useSetOrganizationCallHandling(session);
  // The row that saved shows pending and the error face on its save bar, with the refusal
  // beside it; the bar closes on success, so the success is a toast.
  const feedback = useActionFeedback(save, { errorDisplay: "inline", successToast: "Call settings saved" });
  const write = useWriteAccess(session, "org:manage", "change how your agents end turns and calls");

  const data = state.data;
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
          {
            key: "if_the_caller_goes_quiet",
            label: "What agents do when the caller goes quiet, unless an agent has its own",
            value: silenceSummary(
              state.data.nudge_after_seconds_effective,
              state.data.nudge_count_effective,
              state.data.end_after_silence_seconds_effective,
            ),
          },
          {
            key: "lines_while_looking_up",
            label: "Lines agents say while they look something up",
            value: fillerSummary(state.data.filler_lines_effective),
          },
          {
            key: "background_sound",
            label: "Background sound on calls",
            value: ambienceSummary(
              state.data.ambience_effective,
              state.data.ambience_volume_pct_effective,
            ),
          },
          {
            key: "agents_with_own",
            label: "Agents that do not follow these defaults, and what they use instead",
            value: agentOverridesSummary(state.data),
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
          <CallHandlingDefaultsRows
            data={data}
            save={save}
            status={feedback.status}
            canChange={write.allowed}
            // Call handling is the first thing on an agent's Settings.
            agentHref={(agentId) => href(`/c/${session.orgSlug}/agents/${agentId}?section=settings`)}
          />
        </>
      )}
    </div>
  );
}

