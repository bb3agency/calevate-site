"use client";

/**
 * ADVANCED — the things set once: what the agent is, the model it thinks with, what it can
 * do mid-call, and deleting it. Each set-once panel stays a closed `Disclosure` whose
 * closed state names the fact, so the section reads as four lines until one is opened.
 *
 * Delete is foreground, not disclosed: it is rare but high-consequence, and doctrine §3's
 * table never discloses those. Its consequences are stated above the button that does it.
 */

import { PlugZap, Settings2 } from "lucide-react";

import { Disclosure } from "@/components/ui";
import { movesFor } from "@/lib/agentState";
import type { Agent } from "@/lib/api/agents";
import { useClientSession } from "@/lib/api/session";

import { Actions } from "../../actions/Actions";
import { AgentIdentity } from "../../AgentIdentity";
import { AgentLifecycle } from "../../AgentLifecycle";
import { AgentModel } from "../../AgentModel";

export function AdvancedSection({ agent, slug }: { agent: Agent; slug: string }) {
  const session = useClientSession();
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

      <Disclosure
        title="What it can do during a call"
        subtitle="Send a WhatsApp, look something up, book a slot — and the saved credentials they use."
        icon={<PlugZap className="h-4 w-4" />}
      >
        <Actions agentId={agent.id} session={session} />
      </Disclosure>

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
