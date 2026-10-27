"use client";

/**
 * CALLER FOLLOWS ALONG ON A SCREEN (D-906): for an agent that walks callers through an app or
 * a website while they hold the phone. Off by default, because an agent talking to someone who
 * sees nothing must not name buttons.
 *
 * The limit note is the server's fact (`caller_has_screen_limited`), not this screen's guess:
 * while the voice platform's own call rules are in force, a general rule against mentioning
 * buttons still reaches the agent on live calls, and the owner should hear a test call before
 * relying on it.
 */

import { HowItWorks } from "@/components/console/howItWorks";
import { useActionFeedback } from "@/components/arc/feedback";
import { NoticeBox, ProblemNotice, ToggleSwitch } from "@/components/ui";
import { useSetCallerScreen, type Agent } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";

export function CallerScreen({ agent }: { agent: Agent }) {
  const session = useClientSession();
  const setScreen = useSetCallerScreen(session, agent.id);
  useActionFeedback(setScreen, { errorDisplay: "inline" });
  const write = useWriteAccess(session, "org:manage", "change how this agent guides callers");
  return (
    <section>
      <h3 className="text-heading text-ink">Caller follows along on a screen</h3>
      <p className="mt-1 text-body text-ink-muted">
        For calls that walk someone through your app or website, one step at a time.
      </p>
      {setScreen.error != null && <ProblemNotice error={setScreen.error} />}
      <div className="mt-4">
        <ToggleSwitch
          label="Guide callers through their screen"
          checked={agent.caller_has_screen}
          disabled={setScreen.isPending || !write.allowed}
          onChange={(next) => setScreen.mutate({ enabled: next })}
        />
        {agent.caller_has_screen && agent.caller_has_screen_limited && (
          <div className="mt-3">
            <NoticeBox tone="neutral" role="status">
              On live calls the agent also hears a general rule not to mention buttons, which
              this switch cannot remove yet. Make a test call before you rely on it.
            </NoticeBox>
          </div>
        )}
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
