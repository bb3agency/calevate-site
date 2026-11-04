"use client";

/**
 * CALLER FOLLOWS ALONG ON A SCREEN (D-906): for an agent that walks callers through an app or
 * a website while they hold the phone. Off by default, because an agent talking to someone who
 * sees nothing must not name buttons.
 *
 * Whether to switch it on is suggested from the business itself: its AI-written analysis
 * (`business_copy.screen_guide`) judges whether its callers use its app or website on a
 * call, and the agent's Overview asks the owner (`ScreenGuideSuggestion`).
 */

import { useEffect, useState } from "react";

import { HowItWorks } from "@/components/console/howItWorks";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { NoticeBox, ProblemNotice, ToggleSwitch } from "@/components/ui";
import { useSetCallerScreen, type Agent } from "@/lib/api/agents";
import { useBusinessCopy } from "@/lib/api/businessCopy";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";

export function CallerScreen({ agent }: { agent: Agent }) {
  const session = useClientSession();
  const setScreen = useSetCallerScreen(session, agent.id);
  useActionFeedback(setScreen, { errorDisplay: "inline" });
  const write = useWriteAccess(session, "org:manage", "change how this agent guides callers");
  const guide = useBusinessCopy(session).data?.screen_guide;
  return (
    <section>
      <h3 className="text-heading text-ink">Caller follows along on a screen</h3>
      <p className="mt-1 text-body text-ink-muted">
        {guide?.suggested ? guide.reason : "For callers using your app or website."}
      </p>
      {setScreen.error != null && <ProblemNotice error={setScreen.error} />}
      {(setScreen.data?.patient_settings?.length ?? 0) > 0 && (
        <p role="status" className="mt-3 text-sm text-ink">
          Callers now get more time to answer.
        </p>
      )}
      <div className="mt-4">
        <ToggleSwitch
          label={guide?.suggested ? "Guide callers through their screen (suggested)" : "Guide callers through their screen"}
          checked={agent.caller_has_screen}
          disabled={setScreen.isPending || !write.allowed}
          onChange={(next) => setScreen.mutate({ enabled: next })}
        />
        <HowItWorks
          items={[
            "The agent says what to tap using the words on the caller's screen.",
            "It gives one step, then waits until the caller says it is done.",
            "If a step did not work, it says that step again, more simply.",
            "It spells a web address one letter at a time.",
            "Leave it off for agents whose callers are not looking at a screen.",
          ]}
        />
      </div>
    </section>
  );
}

/** Per agent, per browser: "Not now" is a convenience, so it lives in this browser only. */
const dismissKey = (agentId: string) => `calevate:screen-guide-not-now:${agentId}`;

/**
 * The question, asked where the owner looks first: when the business's analysis says its
 * callers use its app or website on a call and this agent's switch is off. One button turns
 * it on; "Not now" hides it in this browser.
 */
export function ScreenGuideSuggestion({ agent }: { agent: Agent }) {
  const session = useClientSession();
  const guide = useBusinessCopy(session).data?.screen_guide;
  const setScreen = useSetCallerScreen(session, agent.id);
  const feedback = useActionFeedback(setScreen, { errorDisplay: "inline" });
  const write = useWriteAccess(session, "org:manage", "change how this agent guides callers");
  const [dismissed, setDismissed] = useState(true);
  useEffect(() => {
    try {
      setDismissed(window.localStorage.getItem(dismissKey(agent.id)) === "1");
    } catch {
      setDismissed(false);
    }
  }, [agent.id]);

  if (!guide?.suggested || agent.caller_has_screen || dismissed || !write.allowed) return null;
  return (
    <NoticeBox
      tone="neutral"
      title="Do your callers use your app or website on the call?"
      action={
        <div className="flex flex-wrap gap-2">
          <ActionButton
            variant="primary-sm"
            status={feedback.status}
            onClick={() => feedback.run({ enabled: true })}
            pendingLabel="Turning on…"
            successLabel="On"
          >
            Guide them on screen
          </ActionButton>
          <button
            type="button"
            className="text-meta font-medium text-ink-muted underline underline-offset-2 hover:text-ink"
            onClick={() => {
              try {
                window.localStorage.setItem(dismissKey(agent.id), "1");
              } catch {
                // Private window or blocked storage: it just shows again next time.
              }
              setDismissed(true);
            }}
          >
            Not now
          </button>
        </div>
      }
    >
      <p className="mt-1">{guide.reason}</p>
      {setScreen.error != null && <ProblemNotice error={setScreen.error} />}
    </NoticeBox>
  );
}
