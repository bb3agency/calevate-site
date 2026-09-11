"use client";

/**
 * The route module for a client's phone numbers. It unwraps its params and mounts the
 * screen; the screen is `NumbersScreen.tsx` (UX §6 — a route module keeps the chrome and
 * hands off, and may export only `default`, D-196).
 */

import { use } from "react";

import { NumbersScreen } from "./NumbersScreen";

export default function TenantNumbersPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  return <NumbersScreen tenantId={tenantId} />;
}
