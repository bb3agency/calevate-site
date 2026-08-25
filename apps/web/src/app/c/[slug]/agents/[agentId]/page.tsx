"use client";

import Link from "next/link";
import { use } from "react";
import { ArrowLeft } from "lucide-react";

import { useClientRealm } from "@/lib/api/session";

import { AgentWorkspace } from "./AgentWorkspace";

/**
 * ONE agent — what it says, what it captures, what it can do, and whether it is working.
 *
 * The route module is deliberately THIN: it unwraps the params, renders the back link, and
 * hands off. Everything about the screen's shape — the hierarchy, the three bands, which
 * panels are disclosed — lives in `./AgentWorkspace.tsx`, where it can be read as one
 * subject and where the doc comment explaining WHY sits beside it. A Next route module may
 * export only `default` and route-segment fields (D-196, tests/routeModuleExports), so a
 * route file is the one place in this tree that cannot be split by exporting helpers, and
 * the answer is to keep almost nothing in it.
 */
export default function AgentDetailPage({
  params,
}: {
  params: Promise<{ slug: string; agentId: string }>;
}) {
  const { slug, agentId } = use(params);
  const { href } = useClientRealm();

  return (
    <div className="space-y-5 pb-12">
      <Link
        href={href(`/c/${slug}/agents`)}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-muted hover:text-ink"
      >
        <ArrowLeft aria-hidden className="h-4 w-4" />
        All agents
      </Link>

      <AgentWorkspace slug={slug} agentId={agentId} />
    </div>
  );
}
