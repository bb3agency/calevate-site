"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { CheckCircle2 } from "lucide-react";

import { TEXT_ACTION } from "@/components/console/section";
import { PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/ui";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { NotesStep } from "./NotesStep";
import { ScriptStep } from "./ScriptStep";
import type { CreatedAgent } from "./StartFromJob";
import { VoiceStep } from "./VoiceStep";
import { useScriptWriting } from "./scriptWriting";
import { NEW_AGENT_STEPS, NewAgentRail } from "./setupStep";

/**
 * STEPS 2-4 OF A NEW AGENT, AND THE FINISH (founder, 3 Nov 2026). The agent exists (step 1
 * made it), so each step edits that draft and each can be skipped; the finish screen offers a
 * test call and the agent itself, where everything skipped can still be set.
 *
 * The script's progress is watched from here, from creation on, so the Script step finds it
 * written, or still being written, whatever the owner did on the Voice step.
 */

const AFTER_JOB = ["voice", "script", "notes"] as const;
type StepId = (typeof AFTER_JOB)[number];
type Outcome = "done" | "skipped";

/** Each step's tab on the agent page, for the finish screen's "Set it". */
const TAB: Record<StepId, string> = { voice: "voice", script: "script", notes: "captured" };

export function NewAgentSteps({ slug, agent }: { slug: string; agent: CreatedAgent }) {
  const session = useClientSession();
  const writing = useScriptWriting(session, agent.id);
  const [at, setAt] = useState<StepId | "finish">("voice");
  const [outcomes, setOutcomes] = useState<Partial<Record<StepId, Outcome>>>({});

  useCopilotSurface({
    route: `/c/${slug}/agents/new`,
    title: `New agent: ${agent.name}`,
    realm: "client",
    fields: [],
    facts: [
      { key: "agent_id", label: "Agent id", value: agent.id },
      { key: "agent_name", label: "Agent name", value: agent.name },
      {
        key: "step",
        label: "Step on screen",
        value: at === "finish" ? "finished" : (NEW_AGENT_STEPS.find((step) => step.id === at)?.label ?? at),
      },
      { key: "script", label: "Its script", value: writing.phase === "writing" ? "being written" : writing.phase },
    ],
    apply: noFill,
  });

  const leave = (step: StepId, outcome: Outcome) => {
    setOutcomes((current) => ({ ...current, [step]: outcome }));
    setAt(AFTER_JOB[AFTER_JOB.indexOf(step) + 1] ?? "finish");
  };
  const back = (step: StepId) => setAt(AFTER_JOB[Math.max(0, AFTER_JOB.indexOf(step) - 1)]);

  if (at === "finish") return <Finish slug={slug} agent={agent} outcomes={outcomes} />;

  let body;
  switch (at) {
    case "voice":
      body = (
        <VoiceStep agentId={agent.id} onNext={() => leave("voice", "done")} onSkip={() => leave("voice", "skipped")} />
      );
      break;
    case "script":
      body = (
        <ScriptStep
          slug={slug}
          agentId={agent.id}
          writing={writing}
          onNext={() => leave("script", "done")}
          onSkip={() => leave("script", "skipped")}
          onBack={() => back("script")}
        />
      );
      break;
    case "notes":
      body = (
        <NotesStep
          agentId={agent.id}
          onNext={() => leave("notes", "done")}
          onSkip={() => leave("notes", "skipped")}
          onBack={() => back("notes")}
        />
      );
      break;
  }

  return (
    <div className="space-y-6">
      <NewAgentRail current={AFTER_JOB.indexOf(at) + 1} onGo={(step) => setAt(AFTER_JOB[step - 1])} />
      <div key={at} className="settings-enter">
        {body}
      </div>
    </div>
  );
}

const DONE_LINE: Record<StepId, Record<Outcome, string>> = {
  voice: { done: "Voice chosen", skipped: "Voice skipped" },
  script: { done: "Script checked", skipped: "Script not checked" },
  notes: { done: "Notes checked", skipped: "Notes skipped" },
};

/** The finish: what was set and what was skipped, a test call, and the agent. */
function Finish({
  slug,
  agent,
  outcomes,
}: {
  slug: string;
  agent: CreatedAgent;
  outcomes: Partial<Record<StepId, Outcome>>;
}) {
  const { href } = useClientRealm();
  const page = href(`/c/${slug}/agents/${agent.id}`);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
  }, []);

  return (
    <section aria-labelledby="new-agent-finished" className="settings-enter py-2">
      <CheckCircle2 aria-hidden className="h-7 w-7 text-brand-strong" />
      <h2
        id="new-agent-finished"
        ref={heading}
        tabIndex={-1}
        className="mt-3 text-balance text-title text-ink focus:outline-none"
      >
        {agent.name} is set up
      </h2>
      <p className="mt-1 text-body text-ink-muted">It&apos;s a draft. Test it, then switch it on.</p>

      <ul className="mt-6 divide-y divide-line border-y border-line">
        {AFTER_JOB.map((step) => {
          const outcome = outcomes[step] ?? "skipped";
          return (
            <li key={step} className="flex min-h-11 items-center justify-between gap-3 py-2">
              <span className={`text-body ${outcome === "done" ? "text-ink" : "text-ink-muted"}`}>
                {DONE_LINE[step][outcome]}
              </span>
              <Link href={href(`/c/${slug}/agents/${agent.id}?section=${TAB[step]}`)} className={TEXT_ACTION}>
                {outcome === "done" ? "Change" : "Set it"}
              </Link>
            </li>
          );
        })}
      </ul>

      <div className="mt-6 flex flex-wrap gap-3">
        <Link href={href(`/c/${slug}/agents/${agent.id}?section=training`)} className={PRIMARY_BUTTON}>
          Make a test call
        </Link>
        <Link href={page} className={SECONDARY_BUTTON}>
          Go to the agent
        </Link>
      </div>
    </section>
  );
}
