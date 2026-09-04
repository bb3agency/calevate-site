import { redirectToBillingTab } from "@/lib/billingRedirect";

/**
 * Retired route — see `lib/billingRedirect.ts` (D-525).
 *
 * Calling credit is the "Credits" tab of `/c/{slug}/billing` now. The file stays so that
 * every link already in the world — a bookmark, an email we have sent, a screenshot in a
 * support thread — still lands on the panel it meant.
 */
export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  await redirectToBillingTab(params, searchParams, "credits");
}
