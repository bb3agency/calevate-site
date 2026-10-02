"use client";

import { use } from "react";

import { CreditsScreen } from "./CreditsScreen";

/** A client's wallet (D-661 Money › Credits). The screen is `CreditsScreen`. */
export default function CreditsPage({
  params,
}: {
  // Next 15: `params` is a Promise, unwrapped with React's `use()` in a client component.
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  return <CreditsScreen tenantId={tenantId} />;
}
