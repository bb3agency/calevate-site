"use client";

/**
 * ADVANCED — the things set once: what the agent is, the model it thinks with, and
 * deleting it. Each set-once panel stays a closed `Disclosure` whose closed state names
 * the fact, so the section reads as three lines until one is opened. (What it can do on a
 * call is its own Actions section.)
 *
 * Delete is foreground, not disclosed: it is rare but high-consequence, and doctrine §3's
 * table never discloses those. Its consequences are stated above the button that does it.
 */

import { Settings2 } from "lucide-react";

import { Disclosure } from "@/components/ui";
import { movesFor } from "@/lib/agentState";
import type { Agent } from "@/lib/api/agents";

import { AgentIdentity } from "../../AgentIdentity";
import { AgentLifecycle } from "../../AgentLifecycle";
import { AgentModel } from "../../AgentModel";

export function AdvancedSection({ agent, slug }: { agent: Agent; slug: string }) {
  const canDelete = movesFor(agent.status).includes("archive");
  return (
    <div className="space-y-4">
      <Disclosure
        title="What it is"
        subtitle="Its name, which way its calls go, and the language it speaks. Changing what it does can stop it answering your numbers."
        icon={<Settings2 className="h-4 w-4" />}
      >
        <AgentIdentity agent={agent} />
      </Disclosure>

      {/* Renders nothing on an API build that does not report a model. */}
      <AgentModel agent={agent} slug={slug} />


      <section aria-label="Delete this agent" className="border-t border-line pt-5">
        <div>
          {canDelete ? (
            <AgentLifecycle agent={agent} only={["archive"]} />
          ) : (
            <p className="text-sm text-ink-muted">
              It is working right now. It has to be switched off before it can be deleted —
              use Switch off in the menu at the top of this page.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
