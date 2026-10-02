"use client";

import { use } from "react";

import { SpendScreen } from "./SpendScreen";

/** One client's month, both directions, and their spend cap (D-661 Money › Spend). */
export default function TenantSpendPage({ params }: { params: Promise<{ tenantId: string }> }) {
  const { tenantId } = use(params);
  return <SpendScreen tenantId={tenantId} />;
}
