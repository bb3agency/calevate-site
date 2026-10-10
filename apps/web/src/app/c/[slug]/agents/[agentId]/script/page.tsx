"use client";

import { use } from "react";

import { useClientRealm } from "@/lib/api/session";

import { ScriptBuilder } from "./ScriptBuilder";

/**
 * The script builder, on its own route because it has its own unsaved state and its own
 * autosaved draft and "Put it live" (doctrine §3). The route module stays thin (D-196).
 */
export default function AgentScriptPage({
  params,
}: {
  params: Promise<{ slug: string; agentId: string }>;
}) {
  const { slug, agentId } = use(params);
  const { href } = useClientRealm();
  return (
    <div className="pb-16">
      <ScriptBuilder
        agentId={agentId}
        backHref={href(`/c/${slug}/agents/${agentId}?section=script`)}
        knowledgeHref={href(`/c/${slug}/knowledge`)}
      />
    </div>
  );
}
