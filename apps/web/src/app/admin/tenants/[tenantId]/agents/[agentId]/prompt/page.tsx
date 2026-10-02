"use client";

import { use } from "react";

import { AgentPromptScreen } from "./AgentPromptScreen";

/** The route is chrome only (UX-DOCTRINE §6, D-196): the screen is `AgentPromptScreen`. */
export default function AgentPromptPage({
  params,
}: {
  params: Promise<{ tenantId: string; agentId: string }>;
}) {
  const { tenantId, agentId } = use(params);
  return <AgentPromptScreen tenantId={tenantId} agentId={agentId} />;
}
