"use client";

import { use } from "react";

import { WIDE_RAIL } from "@/components/ui";
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
    // The wide rail: the flow picture and the editor beside it use the width a desktop has.
    <div {...WIDE_RAIL}>
      <ScriptBuilder
        agentId={agentId}
        backHref={href(`/c/${slug}/agents/${agentId}?section=script`)}
        knowledgeHref={href(`/c/${slug}/knowledge`)}
      />
    </div>
  );
}
