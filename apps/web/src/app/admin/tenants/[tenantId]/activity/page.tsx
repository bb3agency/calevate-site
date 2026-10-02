"use client";

import { use } from "react";

import { ActivityScreen } from "./ActivityScreen";

export default function TenantActivityPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  return <ActivityScreen tenantId={tenantId} />;
}
