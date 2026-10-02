"use client";

import { use } from "react";

import { KycScreen } from "./KycScreen";

export default function TenantKycPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  return <KycScreen tenantId={tenantId} />;
}
