"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { CheckCircle2 } from "lucide-react";

import { TEXT_ACTION } from "@/components/console/section";
import { useClientRealm } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { GiveItAJob } from "./CreatedPanel";
import type { CreatedAgent } from "./NameStep";
import { VoiceStep } from "./VoiceStep";
import { NEW_AGENT_STEPS, NewAgentRail } from "./setupStep";
import { NEW_AGENT } from "../../_ui/copy";

/**
 * STEP 2 OF A NEW AGENT, AND THE FINISH (founder, 16 Nov 2026: name, voice, done). The agent
 * exists (step 1 made it), so the voice step edits that draft and can be skipped; the finish
 * gives it a job, an Inbound line or a campaign, because that is where what it says is
 * written. Trying it on the business alone is on its own page.
 */
export function NewAgentSteps({ slug, agent }: { slug: string; agent: CreatedAgent }) {
  const [at, setAt] = useState<"voice" | "finish">("voice");
  const [voice, setVoice] = useState<"done" | "skipped" | null>(null);

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
        value: at === "finish" ? "finished: give it a job" : (NEW_AGENT_STEPS[1]?.label ?? at),
      },
    ],
    apply: noFill,
  });

  if (at === "finish") return <Finish slug={slug} agent={agent} voice={voice ?? "skipped"} />;

  return (
    <div className="space-y-6">
      <NewAgentRail current={1} />
      <div className="settings-enter">
        <VoiceStep
          agentId={agent.id}
          onNext={() => {
            setVoice("done");
            setAt("finish");
          }}
          onSkip={() => {
            setVoice("skipped");
            setAt("finish");
          }}
        />
      </div>
    </div>
  );
}

/** The finish: the agent is made; give it a job, or open it. */
function Finish({ slug, agent, voice }: { slug: string; agent: CreatedAgent; voice: "done" | "skipped" }) {
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
      <p className="mt-1 text-body text-ink-muted">
        {voice === "done" ? "Voice chosen." : "Voice not chosen yet."} Now give it a job.
      </p>
      <p className="mt-1 text-meta text-ink-muted">{NEW_AGENT.jobHint}</p>

      <div className="mt-6">
        <GiveItAJob agentId={agent.id} slug={slug} />
      </div>
      <div className="mt-6 flex flex-wrap gap-x-5 gap-y-2">
        <Link href={href(`/c/${slug}/agents/${agent.id}?section=training`)} className={TEXT_ACTION}>
          Try it on your business
        </Link>
        <Link href={page} className={TEXT_ACTION}>
          Go to the agent
        </Link>
        {voice === "skipped" ? (
          <Link href={href(`/c/${slug}/agents/${agent.id}?section=voice`)} className={TEXT_ACTION}>
            Choose a voice
          </Link>
        ) : null}
      </div>
    </section>
  );
}
