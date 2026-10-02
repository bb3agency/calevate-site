"use client";

import { use } from "react";

import { InvoiceScreen } from "./InvoiceScreen";

/** Ops's copy of one client's statement (D-661 Money › Invoice). */
export default function TenantInvoicePage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  return <InvoiceScreen tenantId={tenantId} />;
}
