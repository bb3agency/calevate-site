"use client";

import { use, type ReactNode } from "react";

import { TenantShell } from "./TenantShell";

/** One client's pages share a header and a section menu (D-661); see `TenantShell`. */
export default function TenantLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  return <TenantShell tenantId={tenantId}>{children}</TenantShell>;
}
