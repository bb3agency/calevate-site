"use client";

import type { ReactNode } from "react";

import type { Agent } from "@/lib/api/agents";

import { AgentIdentity } from "../../AgentIdentity";
import { AgentModel } from "../../AgentModel";
import { ExtractionList } from "../../panels/extraction";

/**
 * The body of a deleted agent's page: read-only, what it captured, what it was and its
 * model. Its own module so a live agent's page never downloads it.
 */
export function DeletedAgentBody({ agent, slug, leadsLink }: { agent: Agent; slug: string; leadsLink: ReactNode }) {
  return (
    <>
      <ExtractionList agent={agent} leadsHref={leadsLink} />
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
