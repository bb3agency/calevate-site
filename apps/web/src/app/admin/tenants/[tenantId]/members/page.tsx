"use client";

import { use } from "react";

import { PeopleScreen } from "./PeopleScreen";

/** The route is chrome only (UX-DOCTRINE §6, D-196): the screen is `PeopleScreen`. */
export default function TenantMembersPage({ params }: { params: Promise<{ tenantId: string }> }) {
  const { tenantId } = use(params);
  return <PeopleScreen tenantId={tenantId} />;
}
