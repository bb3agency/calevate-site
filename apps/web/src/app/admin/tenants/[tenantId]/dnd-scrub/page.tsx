"use client";

import { use } from "react";

import { ScrubScreen } from "./ScrubScreen";

export default function PreferenceScrubPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  return <ScrubScreen tenantId={tenantId} />;
}
