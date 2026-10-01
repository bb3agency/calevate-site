"use client";

import { use } from "react";

import { AgentWorkspace } from "./AgentWorkspace";

/**
 * ONE agent's workspace. The route module stays thin because a Next route module may export
 * only `default` and route-segment fields (D-196, tests/routeModuleExports); the screen's
 * shape lives in `./AgentWorkspace.tsx`.
 */
export default function AgentDetailPage({
  params,
}: {
  params: Promise<{ slug: string; agentId: string }>;
}) {
  const { slug, agentId } = use(params);
  return (
    <div className="pb-12">
      <AgentWorkspace slug={slug} agentId={agentId} />
    </div>
  );
}
