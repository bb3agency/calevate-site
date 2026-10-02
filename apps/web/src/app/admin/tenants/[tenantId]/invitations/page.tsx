import { redirect } from "next/navigation";

/**
 * Invitations live on the People page now (D-661): members and the links still waiting to
 * be redeemed are one list. This route stays so a bookmark or an old link lands there.
 */
export default async function TenantInvitationsPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = await params;
  redirect(`/admin/tenants/${encodeURIComponent(tenantId)}/members`);
}
