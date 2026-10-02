"use client";

import { use } from "react";

import { CommercialsScreen } from "./CommercialsScreen";

/** What a client pays, and every dated agreement behind it (D-661 Money › Commercials). */
export default function CommercialsPage({
  params,
}: {
  // Next 15: `params` is a Promise, unwrapped with React's `use()` in a client component.
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  return <CommercialsScreen tenantId={tenantId} />;
}
