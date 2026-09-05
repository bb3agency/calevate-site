import { redirectToBillingTab } from "@/lib/billingRedirect";

/**
 * Retired route — see `lib/billingRedirect.ts` (D-525).
 *
 * Usage is the "Usage" tab of `/c/{slug}/billing` now, alongside the per-agent and
 * per-call breakdown that used to be a separate screen. The file stays so that every link
 * already in the world still lands on the panel it meant.
 */
export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  await redirectToBillingTab(params, searchParams, "usage");
}
