"use client";

import { use } from "react";

import { ClosureScreen } from "./ClosureScreen";

export default function ClosurePage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  return <ClosureScreen tenantId={tenantId} />;
}
