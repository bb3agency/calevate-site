import { redirectToBillingTab } from "@/lib/billingRedirect";

/**
 * Retired route — see `lib/billingRedirect.ts` (D-525).
 *
 * Spend is the second half of the "Usage" tab of `/c/{slug}/billing` now — the same
 * per-agent and per-call breakdown, under the month's totals it itemises, which is the
 * order the question is actually asked in. The file stays so that every link already in
 * the world still lands on the panel it meant.
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
