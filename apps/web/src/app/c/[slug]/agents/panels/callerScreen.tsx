"use client";

/**
 * CALLER FOLLOWS ALONG ON A SCREEN (D-906): for an agent that walks callers through an app or
 * a website while they hold the phone. Off by default, because an agent talking to someone who
 * sees nothing must not name buttons.
 *
 * Whether to switch it on, and "Give callers time" (D-907) with it, is judged per agent from
 * what that agent does: its script, its small steps and its campaigns (founder, 5 Nov 2026;
 * `lib/api/callerHelp.ts`). The Overview asks the owner once (`CallerHelpSuggestion`); the
 * Settings rows say which is suggested for this agent and why.
 */

import { HowItWorks } from "@/components/console/howItWorks";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { NoticeBox, ProblemNotice, ToggleSwitch } from "@/components/ui";
import { useSetCallerScreen, type Agent } from "@/lib/api/agents";
import {
  useCallerHelp,
  useDismissCallerHelp,
  useTurnOnCallerHelp,
  type CallerHelpItem,
} from "@/lib/api/callerHelp";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";

/** "Suggested for Varsha: …", the line a Settings row shows under its name. */
export function suggestedFor(agentName: string, item: CallerHelpItem | undefined): string | null {
  return item?.suggested && item.reason ? `Suggested for ${agentName}: ${item.reason}` : null;
}

export function CallerScreen({ agent }: { agent: Agent }) {
  const session = useClientSession();
  const setScreen = useSetCallerScreen(session, agent.id);
  useActionFeedback(setScreen, { errorDisplay: "inline" });
  const write = useWriteAccess(session, "org:manage", "change how this agent guides callers");
  const suggested = suggestedFor(agent.name, useCallerHelp(session, agent.id).data?.screen_guide);
  return (
    <section>
      <h3 className="text-heading text-ink">Caller follows along on a screen</h3>
      <p className="mt-1 text-body text-ink-muted">
        {suggested ?? "For callers using your app or website."}
      </p>
      {setScreen.error != null && <ProblemNotice error={setScreen.error} />}
      {(setScreen.data?.give_callers_time_settings?.length ?? 0) > 0 && (
        <p role="status" className="mt-3 text-sm text-ink">
          Callers now get more time to answer.
        </p>
      )}
      <div className="mt-4">
        <ToggleSwitch
          label="Guide callers through their screen"
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

/**
 * The one question on the Overview, asked when this agent's own judgement suggests the screen
 * guide, "Give callers time", or both, and the owner has neither turned it on nor said "Not
 * now". One button turns on what is suggested; "Not now" is kept on the server, so it is not
 * asked again on another device. The reason is the judgement's, drawn from the agent's script;
 * what each setting does sits behind the ⓘ.
 */
export function CallerHelpSuggestion({ agent }: { agent: Agent }) {
  const session = useClientSession();
  const write = useWriteAccess(session, "org:manage", "change how this agent guides callers");
  const help = useCallerHelp(session, agent.id, { enabled: write.allowed });
  const turnOn = useTurnOnCallerHelp(session, agent.id);
  const turnOnFeedback = useActionFeedback(turnOn, { errorDisplay: "inline" });
  const notNow = useDismissCallerHelp(session, agent.id);
  const notNowFeedback = useActionFeedback(notNow, { errorDisplay: "inline" });

  const data = help.data;
  if (!write.allowed || !data) return null;
  const screen = data.screen_guide.ask;
  const time = data.give_time.ask;
  if (!screen && !time) return null;

  const reason = screen ? data.screen_guide.reason : data.give_time.reason;
  const label = screen && time ? "Turn both on" : screen ? "Guide them on screen" : "Give them time";
  const busy = turnOn.isPending || notNow.isPending;
  return (
    <NoticeBox
      tone="info"
      title={
        screen
          ? `Do ${agent.name}'s callers follow along on their phone?`
          : `Do ${agent.name}'s callers need time to do what it asks?`
      }
      infoLabel="what these settings do"
      info={
        <ul className="list-disc space-y-1 pl-4">
          {screen && (
            <li>
              Guide callers on screen: the agent names what to tap and gives one step at a time.
            </li>
          )}
          {time && (
            <li>
              Give callers time: it waits while they do it, instead of asking again or hanging
              up.
            </li>
          )}
          <li>You can change either on the Settings tab.</li>
        </ul>
      }
      action={
        <div className="flex flex-wrap items-center gap-3">
          <ActionButton
            variant="primary-sm"
            status={turnOnFeedback.status}
            disabled={busy}
            onClick={() => turnOnFeedback.run({ screenGuide: screen, giveTime: time })}
            pendingLabel="Turning on…"
            successLabel="On"
          >
            {label}
          </ActionButton>
          <button
            type="button"
            disabled={busy}
            aria-busy={notNow.isPending || undefined}
            className="text-meta font-medium text-ink-muted underline underline-offset-2 hover:text-ink disabled:opacity-60"
            onClick={() => notNowFeedback.run()}
          >
            Not now
          </button>
        </div>
      }
    >
      <p>{reason}</p>
      {turnOn.error != null && <ProblemNotice error={turnOn.error} />}
      {notNow.error != null && <ProblemNotice error={notNow.error} />}
    </NoticeBox>
  );
}
