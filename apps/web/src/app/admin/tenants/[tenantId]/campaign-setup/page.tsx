"use client";

import { use } from "react";

import { useTenant } from "@/lib/api/admin";

import { CampaignSetup } from "../CampaignSetup";

/**
 * Campaign setup (Compliance): the registrar's verdicts on numbers and templates, and the
 * client's DLT entity registration — the per-client prerequisites every campaign stalls on.
 *
 * The panel's own title is this page's `h2`; the tenant layout prints the client's name as
 * the `h1` and has already resolved the tenant read, so this is a cache hit.
 */
export default function TenantCampaignSetupPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  const tenant = useTenant(tenantId).data;
  if (!tenant) return null;
  return <CampaignSetup tenantId={tenantId} slug={tenant.slug} />;
}
