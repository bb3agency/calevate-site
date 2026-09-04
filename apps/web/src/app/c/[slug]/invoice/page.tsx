import { redirectToBillingTab } from "@/lib/billingRedirect";

/**
 * Retired route — see `lib/billingRedirect.ts` (D-525).
 *
 * The statement is on the "Transactions" tab of `/c/{slug}/billing` now, beside the wallet
 * movements and the receipts it accounts for. The file stays so that every link already in
 * the world — a bookmark, an email we have sent — still lands on the panel it meant.
 */
export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  await redirectToBillingTab(params, searchParams, "transactions");
}
