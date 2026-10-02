"use client";

import { use } from "react";

import { AgentsScreen } from "./AgentsScreen";

/** The route is chrome only (UX-DOCTRINE §6, D-196): the screen lives in `AgentsScreen`. */
export default function TenantAgentsPage({ params }: { params: Promise<{ tenantId: string }> }) {
  const { tenantId } = use(params);
  return <AgentsScreen tenantId={tenantId} />;
}
