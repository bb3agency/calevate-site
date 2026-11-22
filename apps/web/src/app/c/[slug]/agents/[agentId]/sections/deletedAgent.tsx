"use client";

import type { Agent } from "@/lib/api/agents";

import { AgentIdentity } from "../../AgentIdentity";
import { AgentModel } from "../../AgentModel";

/**
 * The body of a deleted agent's page: read-only, what it was and its model. Its own module
 * so a live agent's page never downloads it.
 */
export function DeletedAgentBody({ agent, slug }: { agent: Agent; slug: string }) {
  return (
    <>
      <section aria-labelledby="deleted-identity-heading">
        <h3 id="deleted-identity-heading" className="mb-2 text-heading text-ink">
          What it is
        </h3>
        <AgentIdentity agent={agent} />
      </section>
      <AgentModel agent={agent} slug={slug} />
    </>
  );
}
